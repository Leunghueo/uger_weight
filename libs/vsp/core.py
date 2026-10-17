from __future__ import annotations

import json
import logging
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from segs import SegmentMapping
except ModuleNotFoundError:  # pragma: no cover - fallback for package imports
    from main.libs.segs import SegmentMapping

ParserFunc = Callable[[bytes], float]
PARSERS: dict[str, ParserFunc] = {}

def parser(name: str) -> Callable[[ParserFunc], ParserFunc]:
    def decorator(func: ParserFunc) -> ParserFunc:
        PARSERS[name] = func
        return func

    return decorator


def parse_hex_cmd(raw: Any) -> bytes:
    text = str(raw or "").replace(" ", "").replace("\t", "").replace("\r", "").replace("\n", "")
    if not text:
        raise ValueError("cmd is required")
    if len(text) % 2 != 0:
        raise ValueError(f"hex command length must be even: {raw!r}")
    try:
        return bytes.fromhex(text)
    except ValueError as exc:
        raise ValueError(f"invalid hex command: {raw!r}") from exc


@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int

    @classmethod
    def parse(cls, raw: Any) -> "Endpoint":
        text = str(raw).strip()
        host, port_text = text.split("@", 1)
        return cls(host=host.strip(), port=int(port_text))


@dataclass(frozen=True)
class VSPPointConfig:
    name: str
    endpoint: Endpoint
    read_cmd: bytes
    zero_cmd: bytes | None
    parser_name: str
    segs: SegmentMapping
    unit: str | None
    add: float

    def _cmd_hex(self, cmd: bytes | None) -> str | None:
        return " ".join(f"{byte:02X}" for byte in cmd) if cmd else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "addr": f"{self.endpoint.host}@{self.endpoint.port}",
            "cmd": {
                "read": self._cmd_hex(self.read_cmd),
                "zero": self._cmd_hex(self.zero_cmd),
            },
            "parser": self.parser_name,
            "segs": [f"{segment.source:g}@{segment.target:g}" for segment in self.segs.segments],
            "unit": self.unit,
        }


def parse_cmds(raw: Any) -> tuple[bytes, bytes | None]:
    """解析点位指令配置.

    新格式: {"read": "<hex>", "zero": "<hex>"}；兼容旧格式: "<hex>"（仅 read）。
    返回 (read_cmd, zero_cmd)。
    """
    if isinstance(raw, dict):
        read_cmd = parse_hex_cmd(raw.get("read"))
        zero_raw = raw.get("zero")
        zero_cmd = parse_hex_cmd(zero_raw) if zero_raw else None
        return read_cmd, zero_cmd
    return parse_hex_cmd(raw), None


class VSPPoint:
    def __init__(self, config: VSPPointConfig) -> None:
        self.config = config
        self.alive = False
        self.raw_value: float | None = None
        self.value: float | None = None
        self.error: str = ""
        self.updated_at: float | None = None

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def unit(self) -> str | None:
        return self.config.unit

    @property
    def endpoint(self) -> Endpoint:
        return self.config.endpoint

    def update(self, raw_value: float) -> None:
        self.raw_value = raw_value
        self.value = round(self.config.segs.apply(raw_value)+self.config.add,3)
        self.alive = True
        self.error = ""
        self.updated_at = time.time()

    def mark_error(self, error: str) -> None:
        print("vsp err")
        self.value = None
        self.alive = False
        self.error = error
        self.updated_at = time.time()

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "addr": f"{self.endpoint.host}@{self.endpoint.port}",
            "alive": self.alive,
            "raw_value": self.raw_value,
            "value": self.value,
            "unit": self.unit,
            "error": self.error,
            "updated_at": self.updated_at,
        }


class TCPValueClient:
    def __init__(
        self,
        host: str,
        port: int,
        timeout: float,
        recv_bytes: int,
        cmd: bytes,
        parser_func: ParserFunc,
        expect_binary: bool,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.recv_bytes = recv_bytes
        self.cmd = cmd
        self.parser_func = parser_func
        self.expect_binary = expect_binary

    def request(self) -> bytes:
        """发送指令并返回原始应答字节（不解析）。"""
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
            sock.settimeout(self.timeout)
            sock.sendall(self.cmd)
            if self.expect_binary:
                payload = self._recv_binary_packet(sock)
            else:
                payload = self._recv_text_payload(sock)
        if not payload:
            raise ValueError("empty payload")
        return payload

    def read_value(self) -> float:
        return self.parser_func(self.request())

    def _recv_binary_packet(self, sock: socket.socket) -> bytes:
        header = self._recv_exact(sock, 3)
        function_code = header[1]
        if function_code & 0x80:
            return header + self._recv_exact(sock, 2)

        byte_count = header[2]
        return header + self._recv_exact(sock, byte_count + 2)

    def _recv_text_payload(self, sock: socket.socket) -> bytes:
        chunks: list[bytes] = []
        while True:
            try:
                chunk = sock.recv(self.recv_bytes)
            except socket.timeout:
                break
            if not chunk:
                break
            chunks.append(chunk)
            if b"\n" in chunk or b"\r" in chunk:
                break
        return b"".join(chunks)

    def _recv_exact(self, sock: socket.socket, size: int) -> bytes:
        chunks: list[bytes] = []
        remaining = size
        while remaining > 0:
            chunk = sock.recv(remaining)
            if not chunk:
                raise IOError("connection closed while receiving payload")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


class VSPTable:
    #: sim 模式下所有点位的统一测试地址（见 app.ini [sim]）
    SIM_ENDPOINT = "localhost@10000"

    def __init__(self, config_path: str | Path, sim: bool = False) -> None:
        config_file = Path(config_path).resolve()
        data = json.loads(config_file.read_text(encoding="utf-8"))
        service_config = data.get("service_config") or {}
        raw_points: dict[str, dict[str, Any]] = data.get("pts") or {}

        self.config_path = config_file
        self.poll_interval_ms = int(service_config.get("poll_interval_ms", 500))
        self.timeout_ms = int(service_config.get("timeout_ms", 300))
        self.recv_bytes = int(service_config.get("recv_bytes", 4096))
        self.points: dict[str, VSPPoint] = {}
        self.broker = None
        self.alive = False
        self.last_poll_at: float | None = None
        self.last_error: str = ""
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.sim = bool(sim)

        for name, point_data in raw_points.items():
            addr = point_data.get("addr") or point_data.get("port")
            if addr is None:
                raise KeyError(f"{name}: missing addr")
            if self.sim:
                # sim 模式：临时用本地测试地址替代真实地址（不写回配置文件）
                addr = self.SIM_ENDPOINT
            read_cmd, zero_cmd = parse_cmds(point_data.get("cmd"))
            point = VSPPoint(
                VSPPointConfig(
                    name=name,
                    endpoint=Endpoint.parse(addr),
                    read_cmd=read_cmd,
                    zero_cmd=zero_cmd,
                    add=point_data.get("add"),
                    parser_name=str(point_data.get("parser") or "").strip(),
                    segs=SegmentMapping.parse(point_data.get("segs")),
                    unit=point_data.get("unit"),
                )
            )
            if point.config.parser_name not in PARSERS:
                raise KeyError(f"{name}: unknown parser {point.config.parser_name!r}")
            self.points[name] = point

    def start(self) -> threading.Thread:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self._thread
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._poll_loop, name="vsp-poller", daemon=True)
            self._thread.start()
            return self._thread

    def stop(self, timeout: float | None = 2.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def reload(self) -> None:
        """原地重载 VSP 配置：仅更新内部数据，不停止轮询线程，不替换实例。

        所有外部引用（broker、runtime 中的实例）均保持有效。
        """
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        service_config = data.get("service_config") or {}
        raw_points: dict[str, dict[str, Any]] = data.get("pts") or {}

        self.poll_interval_ms = int(service_config.get("poll_interval_ms", 500))
        self.timeout_ms = int(service_config.get("timeout_ms", 300))
        self.recv_bytes = int(service_config.get("recv_bytes", 4096))

        # 构建新点位表（锁外完成，不影响轮询线程）
        new_points: dict[str, VSPPoint] = {}
        for name, point_data in raw_points.items():
            addr = point_data.get("addr") or point_data.get("port")
            if addr is None:
                raise KeyError(f"{name}: missing addr")
            point = VSPPoint(
                VSPPointConfig(
                    name=name,
                    endpoint=Endpoint.parse(addr),
                    cmd=parse_hex_cmd(point_data.get("cmd")),
                    add=point_data.get("add"),
                    parser_name=str(point_data.get("parser") or "").strip(),
                    segs=SegmentMapping.parse(point_data.get("segs")),
                    unit=point_data.get("unit"),
                )
            )
            if point.config.parser_name not in PARSERS:
                raise KeyError(f"{name}: unknown parser {point.config.parser_name!r}")
            new_points[name] = point

        # 原子交换：轮询线程的 for 循环已持有旧 dict 的迭代器，不受影响
        with self._lock:
            self.points = new_points
            self.alive = False
            self.last_poll_at = None
            self.last_error = ""

    def read(self, name: str) -> float | None:
        with self._lock:
            return self.points[name].value

    def read_raw(self, name: str) -> float | None:
        with self._lock:
            return self.points[name].raw_value

    def get(self, name: str) -> VSPPoint:
        return self.points[name]

    def zero(self, name: str, timeout: float | None = None) -> bool:
        """向指定点位发送清零指令。

        返回 True 表示指令已发送且收到应答；False 表示无清零指令或通信失败。
        应答内容不解析（清零帧非数据帧）。
        """
        point = self.points[name]
        zero_cmd = point.config.zero_cmd
        if not zero_cmd:
            raise ValueError(f"{name}: no zero command configured")
        try:
            TCPValueClient(
                point.endpoint.host,
                point.endpoint.port,
                timeout=self.timeout_ms / 1000.0 if timeout is None else timeout,
                recv_bytes=self.recv_bytes,
                cmd=zero_cmd,
                parser_func=lambda data: 0.0,
                expect_binary=True,
            ).request()
            return True
        except Exception as exc:
            logger = logging.getLogger(__name__)
            logger.warning("清零 %s 失败: %s", name, exc)
            return False

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "alive": self.alive,
                "running": self.is_running(),
                "last_poll_at": self.last_poll_at,
                "last_error": self.last_error,
                "points": {name: point.snapshot() for name, point in self.points.items()},
            }

    def describe(self) -> dict[str, dict[str, Any]]:
        return {name: point.config.to_dict() for name, point in self.points.items()}

    def update_by_id(self, name: str, segs: list[str], add: float | None = None) -> None:
        if name not in self.points:
            raise KeyError(name)
        seg_mapping = SegmentMapping.parse(segs)

        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        raw_points = payload.get("pts") or {}
        if name not in raw_points:
            raise KeyError(name)
        raw_points[name]["segs"] = list(segs)
        if add is not None:
            raw_points[name]["add"] = add
        self.config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        point = self.points[name]
        config = point.config
        point.config = VSPPointConfig(
            name=config.name,
            endpoint=config.endpoint,
            read_cmd=config.read_cmd,
            zero_cmd=config.zero_cmd,
            parser_name=config.parser_name,
            segs=seg_mapping,
            unit=config.unit,
            add=add if add is not None else config.add,
        )

    def _poll_loop(self) -> None:
        interval = self.poll_interval_ms / 1000.0
        print(f"vsp interval: {interval}")
        while not self._stop_event.is_set():
            started_at = time.time()
            self.poll_once()
            elapsed = time.time() - started_at
            self._stop_event.wait(max(0.0, interval - elapsed))

    def poll_once(self) -> None:
        any_success = False
        last_error = ""
        for point in self.points.values():
            try:
                parser_func = PARSERS[point.config.parser_name]
                raw_value = TCPValueClient(
                    point.endpoint.host,
                    point.endpoint.port,
                    timeout=self.timeout_ms / 1000.0,
                    recv_bytes=self.recv_bytes,
                    cmd=point.config.read_cmd,
                    parser_func=parser_func,
                    expect_binary=point.config.parser_name != "text_number",
                ).read_value()
            except Exception as exc:
                with self._lock:
                    point.mark_error(str(exc))
                last_error = str(exc)
                continue

            with self._lock:
                point.update(raw_value)
                self.alive = True
                self.last_error = ""
            any_success = True

        with self._lock:
            self.alive = any_success and bool(self.points)
            self.last_poll_at = time.time()
            self.last_error = last_error

        broker = self.broker
        if broker is not None:
            broker.publish(
                topic = "vsp_poll",
                alive=self.alive,
                running=self.is_running(),
                last_poll_at=self.last_poll_at,
                error=self.last_error,
            )


def load_vsp(config_path: str | Path, sim: bool = False) -> VSPTable:
    """加载 VSP 点位表.

    sim=True 时所有点位的 port 临时替换为 localhost@10000（本地测试用，
    不写回配置文件）。对应 app.ini [sim] enable。
    """
    return VSPTable(config_path, sim=sim)

@parser("text_number")
def text_number(data: bytes) -> float:
    payload = data.decode("utf-8", errors="ignore").strip()
    if not payload:
        raise ValueError("empty text payload")

    number_chars: list[str] = []
    started = False
    for char in payload:
        if char.isdigit() or char in "+-.eE":
            number_chars.append(char)
            started = True
            continue
        if started:
            break

    if not number_chars:
        raise ValueError(f"no numeric value found in payload: {payload!r}")
    return float("".join(number_chars))

@parser("hex2dis")
def hex2dis(data: bytes) -> float:
    if len(data) < 6:
        raise ValueError(f"hex2dis requires at least 6 bytes, got {len(data)}")

    value_bytes = data[-6:-2]
    raw_value = int.from_bytes(value_bytes, byteorder="big", signed=False)
    return raw_value / 1000

@parser("hex2kg")
def hex2kg(data: bytes) -> float:
    if len(data) < 6:
        raise ValueError(f"hex2dis requires at least 6 bytes, got {len(data)}")

    value_bytes = data[-6:-2]
    raw_value = int.from_bytes(value_bytes, byteorder="big", signed=False)
    return raw_value

@parser("hex2move")
def hex2move(data: bytes) -> float:
    if len(data) < 9:
        raise ValueError(f"hex2dis requires at least 6 bytes, got {len(data)}")

    value_bytes = data[-6:-2]
    raw_value = int.from_bytes(value_bytes, byteorder="big", signed=False)
    return round(raw_value / 65535, 3)

@parser("hex2press")
def hex2press(data: bytes) -> float:
    if len(data) < 9:
        raise ValueError(f"hex2dis requires at least 6 bytes, got {len(data)}")

    value_bytes = data[-6:-2]
    raw_value = int.from_bytes(value_bytes, byteorder="big", signed=False)
    return round(raw_value / 4096 * 6, 3)
