"""VSP 本地模拟测试程序 (串口服务器模拟器)

配合 app.ini [sim] enable=true 使用：程序会把 vsp.json 里所有点位的 port
临时替换为 localhost@10000，因此模拟器默认只监听 127.0.0.1:10000 单端口。

应答逻辑（与 libs/vsp/core.py 的 TCPValueClient / hex2dis 配合）：
- 收到读指令（01 03 00 50 00 02 …）后回复数据帧：
    [01, 03, 04, D1, D2, D3, D4, crc_lo, crc_hi]   共 9 字节
    - 01       从站地址
    - 03       功能码（读保持寄存器，与 read 指令一致）
    - 04       数据字节数（2 个寄存器）
    - D1..D4   32 位大端整数（随机数，默认 16000~20000）
    - CRC16    Modbus CRC，小端附加
- 收到其他指令（如清零指令）后回复短 ACK 帧 [01, 03, 00, crc_lo, crc_hi]。

上位机解析：hex2dis 取 data[-6:-2] 即 D1..D4，按 32 位大端整数解读后 /1000，
再经 segs 标定（如 111.67@676.5 即 ×6.058）得到 kN。
默认随机数 17000~20000 对应约 103~121 kN，落在 maps.json 校验数据
轮重[100,200] 区间内，便于本地联调。

用法：
    python vsp_sim.py                                # 监听 127.0.0.1:10000
    python vsp_sim.py --host 0.0.0.0 --port-start 10000 --port-end 10020
    python vsp_sim.py --min 17000 --max 20000        # 随机数范围
"""
from __future__ import annotations

import argparse
import random
import socket
import sys
import threading

# 读指令特征（vsp.json 中各点位的 read 指令）
READ_CMD = bytes.fromhex("01 03 00 50 00 02 C4 1A")


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def with_crc(payload: bytes) -> bytes:
    return payload + crc16_modbus(payload).to_bytes(2, "little")


class VSPSimulator:
    """应答逻辑：读指令回数据帧，其他指令回短 ACK。"""

    def __init__(self, min_value: int, max_value: int) -> None:
        self.min_value = min_value
        self.max_value = max_value
        self._lock = threading.Lock()

    def build_response(self, request: bytes) -> bytes:
        if request[:8] == READ_CMD:
            with self._lock:
                value = random.randint(self.min_value, self.max_value)
            payload = bytes([0x01, 0x03, 0x04]) + value.to_bytes(4, "big")
            return with_crc(payload)
        # 清零等其他指令：短 ACK
        return with_crc(bytes([0x01, 0x03, 0x00]))


def serve_client(sock: socket.socket, client_addr, sim: VSPSimulator) -> None:
    try:
        while True:
            try:
                request = sock.recv(256)
            except (ConnectionResetError, OSError):
                break
            if not request:
                break
            response = sim.build_response(request)
            sock.sendall(response)
    finally:
        sock.close()


def serve_port(host: str, port: int, sim: VSPSimulator) -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((host, port))
    except OSError as exc:
        print(f"[错误] 监听 {host}:{port} 失败: {exc}")
        return
    server.listen(64)
    print(f"[监听] {host}:{port} 就绪")
    try:
        while True:
            sock, client_addr = server.accept()
            threading.Thread(
                target=serve_client, args=(sock, client_addr, sim), daemon=True
            ).start()
    except OSError:
        pass
    finally:
        server.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="VSP 串口服务器本地模拟器")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址 (默认 127.0.0.1)")
    parser.add_argument("--port-start", type=int, default=10000, help="起始端口 (默认 10000)")
    parser.add_argument("--port-end", type=int, default=10000, help="结束端口 (默认 10000)")
    parser.add_argument("--min", type=int, default=17000, help="随机数下限 (默认 17000)")
    parser.add_argument("--max", type=int, default=20000, help="随机数上限 (默认 20000)")
    args = parser.parse_args()

    if not (0 <= args.min <= args.max <= 0xFFFFFFFF):
        parser.error(f"随机数范围无效: {args.min}-{args.max}")
    if not (0 <= args.port_start <= args.port_end <= 0xFFFF):
        parser.error(f"端口范围无效: {args.port_start}-{args.port_end}")

    sim = VSPSimulator(args.min, args.max)
    print(
        f"VSP 模拟器启动: 监听 {args.host}:{args.port_start}-{args.port_end}, "
        f"读应答 01 03 04 + 32位随机数[{args.min},{args.max}] + CRC"
    )
    for port in range(args.port_start, args.port_end + 1):
        threading.Thread(
            target=serve_port, args=(args.host, port, sim), daemon=True
        ).start()

    print("按 Ctrl+C 退出")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    print("VSP 模拟器已退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
