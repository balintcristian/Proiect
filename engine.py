import asyncio
import multiprocessing
import threading
import random
import time
import math
from datetime import datetime
import concurrent.futures

# SPECIFICATII MOTOR (CONSTANTE DE FABRICA)
# NUMAR_NUCLEE = multiprocessing.cpu_count()
# TEMP_AMBIENTALA = 25.0
# TEMP_NOMINALA = 90.0    
# TEMP_CRITICA = 150.0    
# RATE_RACIRE = 8.0       

# PECIFICATII SARCINA (TASK)
# INCALZIRE_NORMAL = 15.0  
# INCALZIRE_AGRESIV = 60.0 

NUMAR_NUCLEE = multiprocessing.cpu_count()
TEMP_AMBIENTALA = 25.0
TEMP_NOMINALA = 50.0    # Temperatura optima
TEMP_CRITICA = 150.0    # Temperatura de avarie
RATE_RACIRE = 6.0       # Grade disipate pe secunda

INCALZIRE_NORMAL = 25.0  
INCALZIRE_AGRESIV = 90.0 

# --- PARAMETRI UZURA (Legea lui Arrhenius) ---
# Uzura de baza la temperatura nominala (foarte mica)
UZURA_BAZA = 0.05 
# Factor de accelerare (cat de mult penalizam caldura excesiva)
FACTOR_PENALIZARE = 0.05

class Motor:
    def __init__(self, motor_id, log_queue, executor):
        self.motor_id = motor_id
        self.log_queue = log_queue
        self.executor = executor
        self.running = False
        self.queue = asyncio.Queue()
        self._consumer_task = None
        
        # Stare Fizica
        self.temperatura = TEMP_AMBIENTALA
        self.sanatate_izolatie = 100.0 # Procentaj ramas
        self.last_update_time = time.time()

    def _log(self, msg):
        self.log_queue.put((datetime.now(), f"[MOTOR {self.motor_id}] {msg}"))

    def _get_stare_tehnica(self):
        # Clasificare realista a starii motorului
        h = self.sanatate_izolatie
        if h > 95: return "NOU (PERFECT)"
        if h > 80: return "BUN"
        if h > 50: return "UZURA MEDIE"
        if h > 20: return "CRITIC (SERVICE NECESAR)"
        if h > 0:  return "AVARIE IMINENTA"
        return "DEFECT (ARS)"

    async def start(self):
        self.running = True
        self.last_update_time = time.time()
        self._log(f"ONLINE | T: {self.temperatura:.1f}C")
        self._consumer_task = asyncio.create_task(self._proceseaza_coada())

    async def stop(self):
        self.running = False
        if self._consumer_task:
            self._consumer_task.cancel()
        
        stare_text = self._get_stare_tehnica()
        self._log(f"OFFLINE | T_final: {self.temperatura:.1f}C | Sanatate: {self.sanatate_izolatie:.2f}% [{stare_text}]")

    async def adauga_task(self, task_id, este_agresiv):
        if not self.running: return
        # Daca motorul este ars (0%), nu mai accepta comenzi
        if self.sanatate_izolatie <= 0:
            return 
        await self.queue.put((task_id, este_agresiv))

    async def _proceseaza_coada(self):
        while self.running:
            try:
                start_wait = time.time()
                try:
                    pack = await asyncio.wait_for(self.queue.get(), timeout=0.2)
                    task_id, este_agresiv = pack
                except asyncio.TimeoutError:
                    self._update_temp(0.2, sarcina_grade=0)
                    continue

                timp_idle = time.time() - start_wait
                self._update_temp(timp_idle, sarcina_grade=0)

                # Daca inca mai are viata, executa task-ul
                if self.sanatate_izolatie > 0:
                    await self._executa_task(task_id, este_agresiv)
                else:
                    self._log(f"REFUZ {task_id}: Motor defect.")
                
                self.queue.task_done()

            except asyncio.CancelledError:
                break

    def _update_temp(self, durata, sarcina_grade=0.0):
        racire = RATE_RACIRE * durata
        incalzire = sarcina_grade * durata
        noua_temp = self.temperatura + incalzire - racire
        # Temperatura nu scade sub cea ambientala
        self.temperatura = max(TEMP_AMBIENTALA, noua_temp)

    async def _executa_task(self, task_id, este_agresiv):
        # PROTECTIE TERMICA
        if self.temperatura > TEMP_CRITICA:
            self._log(f"PROTECTIE ACTIVA ({self.temperatura:.1f}C). Racire fortata...")
            while self.temperatura > (TEMP_CRITICA - 30):
                await asyncio.sleep(0.5)
                self._update_temp(0.5, sarcina_grade=0)
            self._log(f"RESET PROTECTIE. T={self.temperatura:.1f}C. Se reia lucrul.")

        rata_incalzire = INCALZIRE_AGRESIV if este_agresiv else INCALZIRE_NORMAL
        tip_task = "AGRESIV" if este_agresiv else "NORMAL"
        
        self._log(f"START {task_id} [{tip_task}] | T_start: {self.temperatura:.1f}C")
        
        # Simulare durata variabila
        durata_task = random.uniform(0.5, 0.8)
        
        # Calcule CPU
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self.executor, functie_cpu, [1]*3000)
        await asyncio.sleep(durata_task)

        # Actualizare finala
        self._update_temp(durata_task, sarcina_grade=rata_incalzire)
        hp_inainte = self.sanatate_izolatie
        uzura = self._calculeaza_uzura() # Aici se scade din hp curent
        hp_dupa = self.sanatate_izolatie        
        # Mesaj de avertizare doar daca uzura e semnificativa
        detalii_uzura = f" | HP: {hp_inainte:.2f}% -> {hp_dupa:.2f}% (-{uzura:.2f}%)" if uzura > 1 else f" | HP: {hp_dupa:.2F}% (Stable)"

        self._log(f"GATA {task_id} [{tip_task}] | T: {self.temperatura:.0f}C{detalii_uzura}")

    def _calculeaza_uzura(self):
        # Uzura apare doar daca depasim temperatura nominala (50C)
        delta = max(0, self.temperatura - TEMP_NOMINALA)
        
        if delta == 0:
            scadere = 0.005 # Uzura neglijabila naturala
        else:
            # Formula Exponentiala (Calibrata sa nu distruga instant motorul)
            # La fiecare 10 grade peste, uzura creste
            factor = math.pow(1.5, delta / 10.0) 
            scadere = FACTOR_PENALIZARE * factor

        # Aplicam scaderea dar NU coboram sub 0
        noua_sanatate = self.sanatate_izolatie - scadere
        self.sanatate_izolatie = max(0.0, noua_sanatate)
        
        return scadere

def functie_cpu(d): return sum(d)

# --- SYSTEM LOGGER ---
def logger_thread(q):
    with open("monitorizare_motoare.log", "a", encoding="utf-8", buffering=1) as f:
        f.write(f"\n--- SESIUNE NOUA: {datetime.now()} ---\n")
        while True:
            item = q.get()
            if item == "STOP": 
                f.write(f"--- FINAL SESIUNE: {datetime.now()} ---\n")
                break
            ts, msg = item
            log_line = f"[{ts.strftime('%H:%M:%S.%f')[:-3]}] {msg}"
            print(log_line)
            f.write(log_line + "\n")

def log_sys(q, m, wait:bool=True): q.put((datetime.now(), f"[SISTEM] {m}")) if wait else q.putnowait((datetime.now(), f"[SISTEM] {m}")) 

# --- MAIN ---
async def main():
    m = multiprocessing.Manager()
    log_q = m.Queue()
    threading.Thread(target=logger_thread, args=(log_q,), daemon=True).start()

    SANSA_AGRESIV = 0.4 # 40% sansa de task agresiv

    log_sys(log_q, f"Initializare flota: {NUMAR_NUCLEE} motoare.")
    log_sys(log_q, f"Parametri: Nom={TEMP_NOMINALA}C, Crit={TEMP_CRITICA}C")

    with concurrent.futures.ProcessPoolExecutor(max_workers=NUMAR_NUCLEE) as exc:
        motoare = [Motor(i+1, log_q, exc) for i in range(NUMAR_NUCLEE)]
        await asyncio.gather(*(mot.start() for mot in motoare))

        log_sys(log_q, ">>> INCEPE CICLUL DE PRODUCTIE (200 Task-uri) <<<")

        for i in range(200):
            este_agresiv = random.random() < SANSA_AGRESIV
            motor = motoare[i % NUMAR_NUCLEE]
            task_name = f"JOB-{100+i}"
            if este_agresiv: task_name += "-AGR"
            
            await motor.adauga_task(task_name, este_agresiv)
            await asyncio.sleep(0.02) # Ritm rapid

        log_sys(log_q, ">>> Comenzi finalizate. Asteptare executie... <<<")
        await asyncio.gather(*(mot.queue.join() for mot in motoare))
        
        log_sys(log_q, ">>> RAPORT FINAL STARE FLOTA <<<")
        await asyncio.gather(*(mot.stop() for mot in motoare))
        log_q.put("STOP")

if __name__ == "__main__":
    asyncio.run(main())