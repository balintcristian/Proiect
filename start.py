import asyncio
import multiprocessing
import threading
import random
import math
from datetime import datetime
import concurrent.futures
import queue
import matplotlib.pyplot as plt
# --- CONFIGURARE PROCES (SAFE / DURABLE MODE) ---
NUMAR_NUCLEE = multiprocessing.cpu_count()
TEMP_AMBIENTALA = 25.0
TEMP_NOMINALA = 50.0   
TEMP_CRITICA = 150.0   
RATE_RACIRE = 25.0     
# --- PARAMETRI SARCINA ---
INCALZIRE_NORMAL = 15.0
INCALZIRE_AGRESIV = 60 

# --- PARAMETRI VIBRATII (mm/s) ---
VIB_IDLE_MIN = 0.5
VIB_IDLE_MAX = 2.0
VIB_NORMAL = 5.0        
VIB_AGRESIV = 30.0  

# --- PARAMETRI DISTRUGERE () ---
# Termic:
UZURA_BAZA_TERMICA = 0.02 
FACTOR_EXP_TERMIC = 8.0  

# Mecanic (Vibratii):
PRAG_VIB_DAUNA = 15.0    
FACTOR_VIB = 0.05    

class Motor:
    def __init__(self, motor_id, log_queue, executor):
        self.hp_history = [100.0]
        self.task_count=[0]
        self.motor_id = motor_id
        self.log_queue = log_queue
        self.executor = executor
        self.running = False
        self.queue = asyncio.Queue()
        self._consumer_task = None
        self._stopped_logged = False # Flag pentru a preveni logare dubla
        
        # Stare Fizica
        self.temperatura = TEMP_AMBIENTALA
        self.vibratie = 0.0     
        self.sanatate = 100.0   

    def _log(self, msg):
        self.log_queue.put((datetime.now(), f"[MOTOR {self.motor_id}] {msg}"))

    def _get_stare_tehnica(self):
        h = self.sanatate
        if h > 95: return "NOU (RODAT)"
        if h > 80: return "UZURA NORMALA"
        if h > 50: return "UZURA MEDIE"
        if h > 20: return "NECESITA REVIZIE"
        if h > 0:  return "CRITIC"
        return "DEFECT"

    async def start(self):
        self.running = True
        self.vibratie = random.uniform(VIB_IDLE_MIN, VIB_IDLE_MAX)
        self._log(f"ONLINE | T: {self.temperatura:.1f}C | HP: {100}%")
        self._consumer_task = asyncio.create_task(self._proceseaza_coada())

    async def stop(self):
        # PROTECTIE IMPORTANTA: Daca e deja oprit, nu facem nimic.
        if not self.running and self._stopped_logged: return
        
        self.running = False
        
        if self._consumer_task:
            try:
                # Asteptam maxim 1 secunda sa termine ce are de facut
                await asyncio.wait_for(self._consumer_task, timeout=1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                self._consumer_task.cancel()
        
        # Logam o singura data
        if not self._stopped_logged:
            self._stopped_logged = True
            stare_detaliata = self._get_stare_tehnica()
            self._log(f"OFFLINE | Final HP: {max(0.0, self.sanatate):.2f}% [{stare_detaliata}]")

    async def adauga_task(self, task_id, este_agresiv):
        if not self.running: return
        await self.queue.put((task_id, este_agresiv))

    async def _proceseaza_coada(self):
        while self.running:
            try:
                try:
                    pack = await asyncio.wait_for(self.queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    if self.sanatate > 0:
                        self._simulare_fizica(0.1, sarcina=False, agresiv=False)
                    continue

                task_id, este_agresiv = pack

                # Daca e mort, marcam task-ul ca rezolvat si trecem mai departe
                # pentru a nu bloca coada (queue.join)
                if self.sanatate <= 0:
                    self.queue.task_done()
                    continue
                await self._executa_task(task_id, este_agresiv)
                self.queue.task_done()
                self.hp_history.append(self.sanatate)   # <--- append only once per task
                self.task_count.append(len(self.task_count))

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._log(f"ERR: {e}")
                break

    def _simulare_fizica(self, durata, sarcina=False, agresiv=False):
        if self.sanatate <= 0: return 0

        # 1. Temperatura
        racire = RATE_RACIRE * durata
        incalzire_val = 0
        if sarcina:
            temperatura_de_baza = INCALZIRE_AGRESIV if agresiv else INCALZIRE_NORMAL
            incalzire_val = temperatura_de_baza * durata
        
        self.temperatura = max(TEMP_AMBIENTALA, self.temperatura + incalzire_val - racire)

        # 2. Vibratii
        if sarcina:
            base_vib = VIB_AGRESIV if agresiv else VIB_NORMAL
        else:
            base_vib = random.uniform(VIB_IDLE_MIN, VIB_IDLE_MAX)
        
        self.vibratie = base_vib * random.uniform(0.9, 1.1)

        # 3. Uzura
        return self._aplica_uzura(durata)

    def _aplica_uzura(self, durata):
        # A. Uzura Termica
        delta_t = max(0, self.temperatura - TEMP_NOMINALA)
        dauna_termica = 0
        if delta_t > 0:
            dauna_termica = (UZURA_BAZA_TERMICA * math.pow(FACTOR_EXP_TERMIC, delta_t / 30.0)) * durata
        # B. Uzura Mecanica
        dauna_mecanica = 0
        if self.vibratie > PRAG_VIB_DAUNA:
            exces = self.vibratie - PRAG_VIB_DAUNA
            dauna_mecanica = (exces * FACTOR_VIB) * durata

        dauna_totala = dauna_termica + dauna_mecanica
        self.sanatate = max(0.0, self.sanatate - dauna_totala)
        return dauna_totala

    async def _executa_task(self, task_id, este_agresiv):
        tip_task = "A" if este_agresiv else "N"
        durata = random.uniform(0.7, 1.0)
        if self.sanatate <= 0: return
        if self.temperatura > TEMP_CRITICA:
            self._log(f"! PROTECTIE ({self.temperatura:.0f}C). Racire...")
            while self.temperatura > (TEMP_NOMINALA + 40):
                if self.sanatate <= 0 or not self.running: break
                await asyncio.sleep(0.2)
                self._simulare_fizica(0.2, sarcina=False)
            if self.sanatate <= 0: return 
            self._log("REPORNIRE.")
        else:
            self._log(f"inceput {task_id} [{tip_task}] | T:{self.temperatura:.0f}C V:{self.vibratie:.0f}mm/s Hp:{self.sanatate:.1f}%")
        
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self.executor, sum, [1]*5000)
        await asyncio.sleep(durata)
        pierdere = self._simulare_fizica(durata, sarcina=True, agresiv=este_agresiv)

        # Logare inteligenta
        hp_info = ""
        if pierdere > 0.5 or self.sanatate < 50:
             hp_info = f" | Hp: {self.sanatate:.1f}% (-{pierdere:.2f}%)"
        
        if self.sanatate <= 0: 
            hp_info = " [MORT]"
            # Fortam 0.0% vizual daca a murit
            self.sanatate = 0.0

        self._log(f"terminat {task_id} [{tip_task}] | T:{self.temperatura:.0f}C V:{self.vibratie:.0f}mm/s{hp_info}")

# --- LOGGER ---
def logger_thread(q):
    nume_fisier = "motoare_log.txt"
    # Mod 'w' la start pentru a curata sesiunea veche
    with open(nume_fisier, "w", encoding="utf-8") as f:
        f.write(f"{'='*40}\nSIMULARE START: {datetime.now()}\n{'='*40}\n")
    
    while True:
        item = q.get()
        if item == "STOP":
            msg_stop = "--- STOP SESIUNE ---"
            print(msg_stop, flush=True)
            with open(nume_fisier, "a", encoding="utf-8") as f:
                f.write(msg_stop + "\n")
            break
        
        ts, msg = item
        ts_str = ts.strftime('%H:%M:%S')[:-3]
        log_line = f"[{ts_str}] {msg}"
        
        print(log_line, flush=True)
        with open(nume_fisier, "a", encoding="utf-8") as f:
            f.write(log_line + "\n")

def log_sys(q, m): q.put((datetime.now(), f"[SISTEM] {m}"))

# --- MAIN ---
async def main():

    log_q = queue.Queue()
    t_log = threading.Thread(target=logger_thread, args=(log_q,))
    t_log.start()

    log_sys(log_q, f"START SIMULARE ({NUMAR_NUCLEE} MOTOARE)")

    with concurrent.futures.ProcessPoolExecutor(max_workers=NUMAR_NUCLEE) as exc:
        motoare = [Motor(i+1, log_q, exc) for i in range(NUMAR_NUCLEE)]
        await asyncio.gather(*(mot.start() for mot in motoare))

        log_sys(log_q, ">>> SARCINA INTENSIVA (300 JOB-URI) <<<")

        for i in range(300):
            este_agresiv = random.random() < 0.5 
            motor = motoare[i % NUMAR_NUCLEE]
            await motor.adauga_task(f"JOB-{100+i}", este_agresiv)
            await asyncio.sleep(0.005)

        log_sys(log_q, ">>> Asteptare finalizare sarcini... <<<")
        # Asteptam golirea cozilor de executie
        await asyncio.gather(*(mot.queue.join() for mot in motoare))
        
        log_sys(log_q, ">>> Oprire Motoare... <<<")
        # Oprirea este acum idempotenta si sigura
        await asyncio.gather(*(mot.stop() for mot in motoare))
        
        # Semnal de oprire pentru logger DOAR DUPA ce totul e gata
        log_q.put("STOP")

        plt.close()
    # Asteptam thread-ul de logging sa termine scrierea
    t_log.join()
    plt.figure()
    plt.get_current_fig_manager().resize(1080,720)
    for motor in motoare:
        plt.plot(motor.hp_history, label=f"{motor.motor_id+1}")

    plt.xlabel("Evenimente / Job-uri")
    plt.ylabel("HP (%)")
    plt.title("Curba de degradare per motor")
    plt.grid(True)

    # Legendă compactă
    plt.legend(title="Motoare", ncol=4, fontsize=8)  # 4 coloane pentru 16 motoare
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass