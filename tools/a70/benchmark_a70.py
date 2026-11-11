#!/usr/bin/env python3
"""
Galaxy A70 (Snapdragon 675 / 6GB RAM) Resilience & Load Benchmark Suite
Configurable multi-stage stress & resilience benchmark (2 min / 7 min / custom):
1. Multi-Core CPU Compute & Cryptographic Throughput (100% on 8 cores)
2. Real-Time Thermal Curve & Throttling Profiler (1.0s intervals)
3. RAM Bandwidth & LMK Allocation Pressure
4. Storage UFS 2.1 Sequential I/O
5. Gateway & Proxy Service Resilience under Load
Notifies start and detailed completion report via WhatsApp (Evolution API).
"""

import os
import sys
import time
import json
import math
import hashlib
import socket
import argparse
import threading
import multiprocessing
import urllib.request
import urllib.parse
import tempfile
import glob
import re
from typing import Dict, List, Tuple, Any

# Configurações de Notificação
EVOLUTION_API_URL = "https://wa.luisices.com.br"
EVOLUTION_INSTANCE = "homeassistant"
EVOLUTION_API_KEY = "a73c59c3dbaf6728290db85b20fbb9593b8d7088b1df44298f00ec78e34d88b2"
RECIPIENT = "5511975526876"

# Sensores Sysfs do Galaxy A70
THERMAL_ROOT = "/sys/class/thermal"
PATH_CPU_SILVER_FREQ = "/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq"
PATH_CPU_GOLD_FREQ = "/sys/devices/system/cpu/cpu6/cpufreq/scaling_cur_freq"


def send_whatsapp(text: str) -> bool:
    url = f"{EVOLUTION_API_URL}/message/sendText/{urllib.parse.quote(EVOLUTION_INSTANCE)}"
    headers = {
        "apikey": EVOLUTION_API_KEY,
        "Content-Type": "application/json",
        "User-Agent": "A70-Benchmark/1.0",
    }
    payload = json.dumps({"number": RECIPIENT, "text": text.strip()}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status in (200, 201)
    except Exception as e:
        print(f"[Benchmark] Falha ao enviar WhatsApp: {e}", file=sys.stderr)
        return False


def get_thermal_temp(kind: str) -> float | None:
    """Resolve sensors by sysfs type because thermal zone indexes vary."""
    for zone in sorted(glob.glob(os.path.join(THERMAL_ROOT, "thermal_zone*"))):
        try:
            with open(os.path.join(zone, "type")) as f:
                name = f.read().strip().lower()
            tokens = set(re.split(r"[^a-z0-9]+", name))
            matched = ("battery" in name or "batt" in name) if kind == "battery" else (
                any(token in name for token in ("cpu", "soc", "package")) or "ap" in tokens
            )
            if matched:
                with open(os.path.join(zone, "temp")) as f:
                    value = int(f.read().strip())
                return round(value / (1000 if abs(value) >= 1000 else 1), 1)
        except (OSError, ValueError):
            continue
    return None


def get_cpu_temp() -> float | None:
    return get_thermal_temp("cpu")


def get_batt_temp() -> float | None:
    return get_thermal_temp("battery")

def get_frequencies() -> Tuple[int, int]:
    silver_mhz = 0
    gold_mhz = 0
    try:
        with open(PATH_CPU_SILVER_FREQ, "r") as f:
            silver_mhz = int(f.read().strip()) // 1000
    except Exception:
        pass
    try:
        with open(PATH_CPU_GOLD_FREQ, "r") as f:
            gold_mhz = int(f.read().strip()) // 1000
    except Exception:
        pass
    return silver_mhz, gold_mhz


class ThermalTracker:
    def __init__(self):
        self.stop_event = threading.Event()
        self.samples = []
        self.thread = None
        self.cpu_load_active = False

    def set_cpu_load(self, active: bool):
        self.cpu_load_active = active

    def _poll(self):
        while not self.stop_event.is_set():
            t_cpu = get_cpu_temp()
            t_bat = get_batt_temp()
            f_silv, f_gold = get_frequencies()
            self.samples.append({
                "time": time.time(),
                "cpu_temp": t_cpu,
                "batt_temp": t_bat,
                "gold_mhz": f_gold,
                "silver_mhz": f_silv,
                "cpu_load": self.cpu_load_active,
            })
            self.stop_event.wait(1.0)

    def start(self):
        self.stop_event.clear()
        self.samples = []
        self.thread = threading.Thread(target=self._poll, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2.0)

    def summary(self) -> Dict[str, Any]:
        if not self.samples:
            return {}
        cpu_temps = [s["cpu_temp"] for s in self.samples if s["cpu_temp"] is not None]
        batt_temps = [s["batt_temp"] for s in self.samples if s["batt_temp"] is not None]
        gold_freqs = [s["gold_mhz"] for s in self.samples if s["gold_mhz"] > 0]
        loaded_freqs = [s["gold_mhz"] for s in self.samples if s.get("cpu_load") and s["gold_mhz"] > 0]

        return {
            "initial_cpu": cpu_temps[0] if cpu_temps else None,
            "peak_cpu": max(cpu_temps) if cpu_temps else None,
            "final_cpu": cpu_temps[-1] if cpu_temps else None,
            "initial_batt": batt_temps[0] if batt_temps else None,
            "peak_batt": max(batt_temps) if batt_temps else None,
            "final_batt": batt_temps[-1] if batt_temps else None,
            "max_gold_freq": max(gold_freqs) if gold_freqs else 0,
            "min_gold_freq": min(gold_freqs) if gold_freqs else None,
            "min_gold_freq_under_load": min(loaded_freqs) if len(loaded_freqs) >= 3 else None,
            "samples_count": len(self.samples),
        }


def _cpu_worker(duration_sec: float, result_queue: multiprocessing.Queue, stop_event):
    t_end = time.time() + duration_sec
    ops_sha = 0
    ops_math = 0
    chunk = b"X" * (1024 * 1024)  # 1MB buffer

    while time.time() < t_end and not stop_event.is_set():
        hashlib.sha256(chunk).digest()
        ops_sha += 1

        v = 1.0001
        for _ in range(50000):
            v = math.sin(v) * math.cos(v) + math.sqrt(abs(v))
        ops_math += 50000

    result_queue.put((ops_sha, ops_math))


def get_available_memory_mb() -> int | None:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def run_cpu_test(duration_sec: int) -> Dict[str, Any]:
    duration_sec = max(1, duration_sec)
    print(f"==> Estresse limitado de CPU por até {duration_sec}s...", flush=True)
    q = multiprocessing.Queue()
    stop_event = multiprocessing.Event()
    count = max(1, min(8, multiprocessing.cpu_count()))
    procs = []
    started = time.time()
    cpu_deadline = started + duration_sec
    for _ in range(count):
        p = multiprocessing.Process(target=_cpu_worker, args=(duration_sec, q, stop_event))
        p.start()
        procs.append(p)

    aborted_reason = None
    while time.time() < cpu_deadline and any(p.is_alive() for p in procs):
        temperature = get_cpu_temp()
        available_mb = get_available_memory_mb()
        if temperature is not None and temperature >= 75:
            aborted_reason = f"temperatura CPU atingiu {temperature} °C"
            break
        if available_mb is not None and available_mb < 300:
            aborted_reason = f"memória disponível caiu para {available_mb} MB"
            break
        time.sleep(min(0.2, max(0, cpu_deadline - time.time())))

    stop_event.set()
    join_deadline = time.time() + 1.5
    for p in procs:
        p.join(timeout=max(0, join_deadline - time.time()))
    for p in procs:
        if p.is_alive():
            p.terminate()
            p.join(timeout=0.2)

    elapsed = time.time() - started
    total_sha_mb = total_math_ops = completed = 0
    for p in procs:
        try:
            sha, ops = q.get(timeout=0.5)
            total_sha_mb += sha
            total_math_ops += ops
            completed += 1
        except Exception:
            pass
    q.close()
    q.join_thread()
    return {
        "duration": round(elapsed, 1),
        "total_sha_mb": total_sha_mb,
        "sha_mb_s": round(total_sha_mb / max(elapsed, 0.001), 1),
        "math_mops_s": round((total_math_ops / max(elapsed, 0.001)) / 1_000_000, 2),
        "aborted_reason": aborted_reason,
        "workers_completed": completed,
    }

def run_ram_test(num_blocks: int = 4, deadline: float | None = None) -> Dict[str, Any]:
    available = get_available_memory_mb()
    blocks = max(0, min(4, num_blocks, ((available - 512) // 64) if available is not None else 4))
    if blocks < 1:
        return {"allocated_mb": 0, "write_gb_s": None, "read_gb_s": None,
                "skipped_reason": "menos de 576 MB de memória disponível"}
    print(f"==> Teste de RAM limitado a {blocks * 64} MB...", flush=True)
    block_size = 64 * 1024 * 1024
    allocated = []
    t0 = time.time()
    for _ in range(blocks):
        if deadline is not None and time.time() >= deadline - 2.0:
            break
        available = get_available_memory_mb()
        if available is not None and available < 512:
            break
        allocated.append(bytearray(b"\xaa" * block_size))
    written_mb = len(allocated) * 64
    t_write = time.time() - t0
    t1 = time.time()
    checksum = 0
    bytes_read = 0
    chunk_size = 1024 * 1024
    for buf in allocated:
        view = memoryview(buf)
        for offset in range(0, len(view), chunk_size):
            if deadline is not None and time.time() >= deadline - 1.0:
                break
            chunk = view[offset:offset + chunk_size]
            checksum += sum(chunk)
            bytes_read += len(chunk)
        if deadline is not None and time.time() >= deadline - 1.0:
            break
    t_read = time.time() - t1
    del allocated
    import gc
    gc.collect()
    return {
        "allocated_mb": written_mb,
        "write_gb_s": round((written_mb / 1024) / max(t_write, 0.001), 2) if written_mb else None,
        "read_gb_s": round((bytes_read / (1024 ** 3)) / max(t_read, 0.001), 2) if bytes_read else None,
        "bytes_read": bytes_read,
        "checksum": checksum,
    }

def run_storage_test(total_mb: int = 64, deadline: float | None = None) -> Dict[str, Any]:
    total_mb = max(1, min(64, total_mb))
    print(f"==> Teste de armazenamento limitado ({total_mb} MB)...", flush=True)
    data = os.urandom(1024 * 1024)
    fd, path = tempfile.mkstemp(prefix="a70-benchmark-", suffix=".tmp", dir=os.path.expanduser("~"))
    try:
        t0 = time.time()
        written_mb = 0
        with os.fdopen(fd, "wb") as f:
            for _ in range(total_mb):
                if deadline is not None and time.time() >= deadline - 0.5:
                    break
                f.write(data)
                written_mb += 1
            f.flush()
            os.fsync(f.fileno())
        write_elapsed = time.time() - t0
        t1 = time.time()
        bytes_read = 0
        with open(path, "rb") as f:
            while deadline is None or time.time() < deadline - 0.25:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                bytes_read += len(chunk)
        read_elapsed = time.time() - t1
        read_mb = bytes_read / (1024 * 1024)
        return {"file_size_mb": written_mb,
                "write_mb_s": round(written_mb / max(write_elapsed, 0.001), 1),
                "read_mb_s": round(read_mb / max(read_elapsed, 0.001), 1),
                "note": "leitura pode vir do cache do sistema"}
    finally:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

def probe_service(host: str, port: int, timeout: float = 0.15) -> Tuple[bool, float]:
    started = time.time()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, round((time.time() - started) * 1000, 1)
    except OSError:
        return False, 0.0


def run_resilience_test(duration_sec: float = 30) -> Dict[str, Any]:
    duration_sec = max(0.0, duration_sec)
    print(f"==> Monitorando resiliencia e latencia dos servicos locais ({duration_sec:.0f}s)...", flush=True)
    services = [
        ("SSH", 2222),
        ("SOCKS5", 1080),
        ("FTP Relay", 2121),
        ("FireTV Relay", 5555),
        ("WhatsApp Bot", 8088),
    ]
    stats = {name: {"latencies": [], "failures": 0} for name, _ in services}
    deadline = time.time() + duration_sec

    while time.time() < deadline:
        for name, port in services:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            ok, latency = probe_service("127.0.0.1", port, timeout=min(0.05, remaining))
            if ok:
                stats[name]["latencies"].append(latency)
            else:
                stats[name]["failures"] += 1
        remaining = deadline - time.time()
        if remaining > 0:
            time.sleep(min(1.0, remaining))

    results = {}
    for name, values in stats.items():
        latencies = values["latencies"]
        results[name] = {
            "online": values["failures"] == 0 and bool(latencies),
            "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
            "max_latency_ms": max(latencies) if latencies else 0.0,
            "probes_count": len(latencies) + values["failures"],
            "failures": values["failures"],
        }
    return results

def main():
    parser = argparse.ArgumentParser(description="Galaxy A70 Benchmark")
    parser.add_argument("--duration", type=int, default=2, help="Janela de teste em minutos (1 a 10)")
    args = parser.parse_args()
    if args.duration < 1 or args.duration > 10:
        parser.error("--duration deve ficar entre 1 e 10 minutos")

    requested_sec = args.duration * 60
    started = time.time()
    deadline = started + requested_sec
    cpu_duration = max(10, int(requested_sec * 0.40))
    ram_blocks = 1  # teto planejado: 64 MiB; run_ram_test revalida memória disponível
    storage_mb = min(32, max(4, args.duration * 4))
    label_profile = f"limite total de {args.duration} min"
    print(f"Iniciando Benchmark no Galaxy A70 — {label_profile}", flush=True)

    cpu_init = get_cpu_temp()
    batt_init = get_batt_temp()
    _, f_gold_init = get_frequencies()
    temp_label = lambda value: f"{value}°C" if value is not None else "N/D"
    msg_inicio = (
        f"🔥 *[Iniciando Teste de Carga no Galaxy A70 — {args.duration} Minutos]*\n\n"
        f"⚡ *Perfil:* {label_profile}\n"
        "🎯 *Objetivo:* Observar CPU, memória, armazenamento e disponibilidade dos serviços locais com limites de segurança.\n\n"
        "📊 *Condições Iniciais:*\n"
        f"• CPU (Snapdragon 675): *{temp_label(cpu_init)}*\n"
        f"• Bateria: *{temp_label(batt_init)}*\n"
        f"• Clock Kryo Gold: *{f_gold_init} MHz*\n\n"
        "⚙️ *Cronograma do Teste:*\n"
        f"1️⃣ CPU Multi-Core: até *{cpu_duration}s* (interrupção por temperatura/memória)\n"
        f"2️⃣ Pressão de Memória RAM: até *{ram_blocks * 64} MB*\n"
        f"3️⃣ Armazenamento: gravação e leitura de até *{storage_mb} MB* com fsync\n"
        "4️⃣ Serviços: sondagens TCP se houver tempo restante\n\n"
        "⏳ _O relatório detalhado será enviado ao término do teste!_"
    )
    send_whatsapp(msg_inicio)

    tracker = ThermalTracker()
    tracker.start()
    res_cpu = {"duration": 0, "total_sha_mb": 0, "sha_mb_s": 0, "math_mops_s": 0,
               "aborted_reason": "ignorado: sem tempo restante", "workers_completed": 0}
    res_ram = {"allocated_mb": 0, "write_gb_s": None, "read_gb_s": None, "skipped_reason": "sem tempo restante"}
    res_io = {"file_size_mb": 0, "write_mb_s": None, "read_mb_s": None, "skipped_reason": "sem tempo restante"}
    res_serv = {}
    try:
        remaining = max(0, deadline - time.time())
        if remaining > 5:
            tracker.set_cpu_load(True)
            res_cpu = run_cpu_test(min(cpu_duration, int(remaining - 3)))
            tracker.set_cpu_load(False)
        remaining = max(0.0, deadline - time.time())
        if remaining > 10:
            res_ram = run_ram_test(ram_blocks, deadline=deadline)
        remaining = max(0.0, deadline - time.time())
        if remaining > 4:
            res_io = run_storage_test(storage_mb, deadline=deadline)
        remaining = max(0.0, deadline - time.time())
        if remaining > 0.5:
            res_serv = run_resilience_test(max(0.0, remaining - 0.5))
    finally:
        tracker.set_cpu_load(False)
        tracker.stop()
    elapsed_total = round(time.time() - started, 1)
    thermal = tracker.summary()

    gold_min = thermal.get("min_gold_freq_under_load")
    if gold_min is None:
        throttling_status = "N/D (amostras insuficientes durante carga)"
    elif gold_min >= 1900:
        throttling_status = f"sem queda observada (mínimo sob carga: {gold_min} MHz)"
    elif gold_min >= 1600:
        throttling_status = f"queda de clock observada (mínimo: {gold_min} MHz)"
    else:
        throttling_status = f"clock baixo sob carga (mínimo: {gold_min} MHz)"

    serv_lines = []
    for s_name, info in res_serv.items():
        icon = "🟢" if info["online"] else "🔴"
        serv_lines.append(f"• {s_name}: {icon} média {info['avg_latency_ms']}ms; falhas {info['failures']}")
    serv_txt = "\n".join(serv_lines) if serv_lines else "Sondagem não executada (limite de tempo)."
    service_ok = bool(res_serv) and all(item["online"] for item in res_serv.values())
    verdict = "Todos os testes executados concluíram; serviços responderam às sondagens TCP." if service_ok else "Resultado parcial ou uma ou mais sondagens TCP falharam."
    if res_cpu.get("aborted_reason"):
        verdict += f" Estresse de CPU interrompido: {res_cpu['aborted_reason']}."

    results_dump = {
        "timestamp": time.time(), "requested_duration_min": args.duration,
        "actual_duration_sec": elapsed_total, "cpu": res_cpu, "thermal": thermal,
        "ram": res_ram, "storage": res_io, "services": res_serv,
    }
    stamp = time.strftime("%Y%m%d-%H%M%S")
    results_path = os.path.expanduser(f"~/benchmark_results-{stamp}.json")
    try:
        with open(results_path, "x") as f:
            json.dump(results_dump, f, indent=2)
    except OSError as e:
        print(f"Falha ao salvar JSON: {e}", file=sys.stderr)
        results_path = "não salvo"

    def metric(value, suffix=""):
        return f"{value}{suffix}" if value is not None else "N/D"

    cpu_initial = thermal.get("initial_cpu")
    cpu_peak = thermal.get("peak_cpu")
    cpu_final = thermal.get("final_cpu")
    batt_initial = thermal.get("initial_batt")
    batt_peak = thermal.get("peak_batt")
    batt_final = thermal.get("final_batt")
    cpu_delta = round(cpu_peak - cpu_initial, 1) if cpu_peak is not None and cpu_initial is not None else None
    batt_delta = round(batt_peak - batt_initial, 1) if batt_peak is not None and batt_initial is not None else None
    verdict_icon = "✅" if service_ok and not res_cpu.get("aborted_reason") else "⚠️"
    msg_resultado = (
        f"🏁 *Relatório de Carga & Resiliência — Galaxy A70 ({elapsed_total}s / {args.duration} min solicitados)*\n\n"
        f"🔥 *1. Poder de Fogo da CPU (8 Núcleos por {res_cpu['duration']}s):*\n"
        f"• Throughput Criptográfico: *{res_cpu['sha_mb_s']} MB/s* (SHA-256)\n"
        f"• Taxa de Cálculo: *{res_cpu['math_mops_s']} Milhões de ops/s*\n"
        f"• Criptografia Total: *{res_cpu['total_sha_mb']} MB* processados\n"
        f"• Throttling Térmico: *{throttling_status}*\n\n"
        f"🌡️ *2. Curva Térmica:*\n"
        f"• CPU: *{metric(cpu_initial, '°C')}* ➔ Pico *{metric(cpu_peak, '°C')}* ➔ Final *{metric(cpu_final, '°C')}* (ΔT: {metric(cpu_delta, '°C')})\n"
        f"• Bateria: *{metric(batt_initial, '°C')}* ➔ Pico *{metric(batt_peak, '°C')}* ➔ Final *{metric(batt_final, '°C')}* (ΔT: {metric(batt_delta, '°C')})\n"
        f"• Amostras de Temperatura: *{thermal.get('samples_count', 0)} leituras (1/s)*\n\n"
        f"💾 *3. Memória RAM:*\n"
        f"• Taxa de Escrita: *{metric(res_ram.get('write_gb_s'), ' GB/s')}*\n"
        f"• Taxa de Leitura: *{metric(res_ram.get('read_gb_s'), ' GB/s')}*\n"
        f"• Memória Alocada: *{res_ram.get('allocated_mb', 0)} MB*\n\n"
        f"📂 *4. Armazenamento ({res_io.get('file_size_mb', 0)} MB):*\n"
        f"• Escrita Sequencial (fsync): *{metric(res_io.get('write_mb_s'), ' MB/s')}*\n"
        f"• Leitura Sequencial: *{metric(res_io.get('read_mb_s'), ' MB/s')}* (pode usar cache)\n\n"
        f"🔌 *5. Resiliência dos Serviços (sondagens TCP):*\n"
        f"{serv_txt}\n\n"
        f"{verdict_icon} *Veredito do Servidor:*\n{verdict}"
    )
    sent = send_whatsapp(msg_resultado)
    print(f"==> Benchmark finalizado em {elapsed_total}s; relatório {results_path}; WhatsApp {'enviado' if sent else 'não enviado'}.", flush=True)


if __name__ == "__main__":
    main()
