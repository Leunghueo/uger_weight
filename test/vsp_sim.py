"""VSP 本地模拟测试程序 (串口服务器模拟器)

运行后自动监听 10000-10020 全部端口, 每个端口采用相同的应答逻辑:
收到任意查询指令后, 按固定数据格式回复, 数据字节用 500-600 的随机数替代,
并计算/附加正确的 CRC16.

应答帧 (与 libs/vsp/core.py 的 TCPValueClient 配合):
    [01, 04, 04, 00, 00, HI, LO, crc_lo, crc_hi]   共 9 字节
    - 01       从站地址
    - 04       功能码 (读输入寄存器)
    - 04       数据字节数 (2 个寄存器)
    - 00 00    高 16 位 (固定 0)
    - HI LO    低 16 位 = 500-600 随机数
    - CRC16    Modbus CRC, 小端附加

上位机解析 (libs/vsp/core.py): 取 data[-6:-2] 即 4 个数据字节 00 00 HI LO,
按 32 位大端整数解读后交给对应 parser:
    hex2dis  : raw / 1000      -> 0.500 ~ 0.600
    hex2kg   : raw             -> 500 ~ 600
    hex2move : raw / 65535
    hex2press: raw / 4096 * 6

用法:
    python vsp_sim.py                                # 监听 0.0.0.0:10000-10020
    python vsp_sim.py --host 127.0.0.1               # 指定监听地址
    python vsp_sim.py --port-start 10000 --port-end 10020
    python vsp_sim.py --min 500 --max 600            # 随机数范围
"""
from __future__ import annotations

import argparse
import random
import socket
import sys
import threading


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


class VSPSimulator:
    """应答逻辑: 不解析指令内容, 收到任意数据即按固定格式回复随机数据."""

    def __init__(self, min_value: int, max_value: int) -> None:
        self.min_value = min_value
        self.max_value = max_value
        self._lock = threading.Lock()

    def build_response(self) -> bytes:
        with self._lock:
            value = random.randint(self.min_value, self.max_value)
        payload = bytes([0x01, 0x04, 0x04, 0x00, 0x00, (value >> 8) & 0xFF, value & 0xFF])
        return payload + crc16_modbus(payload).to_bytes(2, "little")


def serve_client(sock: socket.socket, client_addr, sim: VSPSimulator) -> None:
    print(f"[连接] {client_addr[0]}:{client_addr[1]}")
    try:
        while True:
            try:
                request = sock.recv(256)
            except (ConnectionResetError, OSError):
                break
            if not request:
                break
            response = sim.build_response()
            sock.sendall(response)
            print(
                f"[数据] {client_addr[0]}:{client_addr[1]} "
                f"请求 {request.hex(' ')}  ->  响应 {response.hex(' ')}"
            )
    finally:
        sock.close()
        print(f"[断开] {client_addr[0]}:{client_addr[1]}")


def serve_port(host: str, port: int, sim: VSPSimulator) -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((host, port))
    except OSError as exc:
        print(f"[错误] 监听 {host}:{port} 失败: {exc}")
        return
    server.listen(16)
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
    parser.add_argument("--host", default="0.0.0.0", help="监听地址 (默认 0.0.0.0)")
    parser.add_argument("--port-start", type=int, default=10000, help="起始端口 (默认 10000)")
    parser.add_argument("--port-end", type=int, default=10020, help="结束端口 (默认 10020)")
    parser.add_argument("--min", type=int, default=500, help="随机数下限 (默认 500)")
    parser.add_argument("--max", type=int, default=600, help="随机数上限 (默认 600)")
    args = parser.parse_args()

    if not (0 <= args.min <= args.max <= 0xFFFF):
        parser.error(f"随机数范围无效: {args.min}-{args.max}")
    if not (0 <= args.port_start <= args.port_end <= 0xFFFF):
        parser.error(f"端口范围无效: {args.port_start}-{args.port_end}")

    sim = VSPSimulator(args.min, args.max)
    print(
        f"VSP 模拟器启动: 监听 {args.host}:{args.port_start}-{args.port_end}, "
        f"应答格式 01 04 04 00 00 XX XX + CRC, 随机数范围 [{args.min},{args.max}]"
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
