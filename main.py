"""
Slurp ($SLURP) - The Hyper-Liquidity Bot
V4.2 Update: ROBUSTNESS (Async Queue + Auto-Pool Switching + Accumulator + RevShare)
"""

import os
import time
import base58
import requests
import json
import threading
import random
import websocket
import queue
from datetime import datetime
from dotenv import load_dotenv
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction, Transaction
from solders.system_program import transfer, TransferParams
from solders.message import Message
from solana.rpc.api import Client
from solders.pubkey import Pubkey


# --- TERMINAL STYLING ---
class Style:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    
    # Foreground
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"


# --- LOGGING SYSTEM ---
LOG_FILE_PATH = "web/public/logs.json"
log_lock = threading.Lock()
log_buffer = []

def init_log_file():
    """Ensure web/public exists and init empty JSON if needed"""
    os.makedirs(os.path.dirname(LOG_FILE_PATH), exist_ok=True)
    if not os.path.exists(LOG_FILE_PATH):
        with open(LOG_FILE_PATH, "w") as f:
            json.dump([], f)

def log(tag: str, msg: str, color: str = Style.WHITE):
    timestamp = datetime.now().strftime("%H:%M:%S")
    
    # 1. Console Output
    print(f"{Style.DIM}[{timestamp}]{Style.RESET} {color}{Style.BOLD}[{tag:^10}]{Style.RESET} {msg}")
    
    # 2. JSON Output for Web UI
    entry = {
        "timestamp": timestamp,
        "tag": tag,
        "msg": msg,
        "color": color.replace("\033", "") # Store raw ansi code part or just the code
    }
    
    with log_lock:
        try:
            # Efficient implementation: In a real high-perf app, we'd append or use a rotating file
            # For this 'simple' request, reading/writing full list is okay up to a few KB.
            # We keep memory buffer to avoid consistent reads, but here we restart often.
            
            # Let's load, append, save to be safe across restarts
            if not os.path.exists(LOG_FILE_PATH): init_log_file()
            
            with open(LOG_FILE_PATH, "r") as f:
                try:
                    data = json.load(f)
                except: data = []
            
            data.append(entry)
            if len(data) > 500: data = data[-500:] # Keep last 500
            
            with open(LOG_FILE_PATH, "w") as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Log Error: {e}")

def print_banner():
    # Attempt to enable ANSI on Windows
    os.system('color') 
    
    banner = f"""{Style.BOLD}{Style.CYAN}
    ██████╗ ██╗     ██╗███████╗███████╗ █████╗ ██████╗ ██████╗ 
    ██╔══██╗██║     ██║╚══███╔╝╚══███╔╝██╔══██╗██╔══██╗██╔══██╗
    ██████╔╝██║     ██║  ███╔╝   ███╔╝ ███████║██████╔╝██║  ██║
    ██╔══██╗██║     ██║ ███╔╝   ███╔╝  ██╔══██║██╔══██╗██║  ██║
    ██████╔╝███████╗██║███████╗███████╗██║  ██║██║  ██║██████╔╝
    ╚═════╝ ╚══════╝╚═╝╚══════╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ 
             {Style.WHITE}>> THE FROZEN LIQUIDITY ENGINE <<{Style.RESET}
    """
    print(banner)
    print(f"{Style.DIM}    v4.4.0 | BLIZZARD PROTOCOL | SYSTEM: FROST ❄️{Style.RESET}\n")

def startup_animation():
    steps = [
        ("INIT", "Freezing local environment...", Style.BLUE, 0.5),
        ("MEMORY", "Compacting snowballs...", Style.CYAN, 0.3),
        ("NET", "Connecting to the Blizzard Stream...", Style.WHITE, 0.4),
        ("SECURE", "Icing safety locks...", Style.GREEN, 0.3),
        ("SYSTEM", "BLIZZARD MODE ENGAGED... ❄️", Style.CYAN, 0.6)
    ]
    for tag, msg, color, delay in steps:
        time.sleep(delay)
        log(tag, msg, color)
    print(f"\n{Style.BOLD}{Style.GREEN}    >> READY TO SIP. WAITING FOR DROPS. <<{Style.RESET}\n")


# --- CONFIGURATION ---
load_dotenv()
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
WORKER_PRIVATE_KEY = os.getenv("WORKER_PRIVATE_KEY")
TOKEN_MINT = os.getenv("TOKEN_MINT")
RPC_URL = os.getenv("RPC_URL", "https://api.mainnet-beta.solana.com")
TRIGGER_THRESHOLD = float(os.getenv("TRIGGER_THRESHOLD", "0.5"))
GAS_RESERVE = float(os.getenv("GAS_RESERVE", "0.02"))
PRIORITY_FEE = float(os.getenv("PRIORITY_FEE", "0.005"))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "1"))
SLIPPAGE = int(os.getenv("SLIPPAGE", "50"))
POOL = os.getenv("POOL", "pump")

# V4.1 ACCUMULATION SETTINGS
BUY_PCT = int(os.getenv("BUY_PCT", "100")) 
SELL_PCT = int(os.getenv("SELL_PCT", "100")) 

# REACTION SETTINGS
REACTION_COOLDOWN = 2.0 

# ORGANIC HEARTBEAT SETTINGS
HOLD_TIME_MIN = int(os.getenv("HOLD_TIME_MIN", "45"))
HOLD_TIME_MAX = int(os.getenv("HOLD_TIME_MAX", "90"))
HEARTBEAT_TIMEOUT = 120 

# FEE CLAIM SETTINGS
CLAIM_INTERVAL_SECONDS = int(os.getenv("CLAIM_INTERVAL_SECONDS", "30"))
DEV_WALLET = os.getenv("DEV_WALLET", "3CNH1A7NDRCJZ28y1Zm7cPhRuhgEMeKsBSs97Ez1gYwx")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

PUMPPORTAL_API = "https://pumpportal.fun/api/trade-local"
PUMPPORTAL_WS = "wss://pumpportal.fun/api/data"
LAMPORTS_PER_SOL = 1_000_000_000

# THREAD SAFETY & QUEUES
state_lock = threading.Lock()
trade_queue = queue.Queue() # Async Signal Queue

# Recent Traders Tracking (for lottery)
from collections import deque
recent_traders = deque(maxlen=100)  # Keep last 100 unique traders
traders_lock = threading.Lock()

# State
position_state = {
    "active": False,
    "entry_time": None,
    "current_hold_target": 0
}
last_action_time = 0
last_market_event_time = time.time()

def load_keypair(env_var="PRIVATE_KEY") -> Keypair:
    try:
        key = os.getenv(env_var)
        if not key:
            raise ValueError(f"Missing {env_var}")
        key = key.strip()
        if key.startswith("[") and key.endswith("]"):
            byte_array = json.loads(key)
            return Keypair.from_bytes(bytes(byte_array))
        else:
            return Keypair.from_bytes(base58.b58decode(key))
    except Exception as e:
        raise ValueError(f"Failed to load keypair from {env_var}: {e}")

def get_sol_balance(client: Client, pubkey_str: str) -> float:
    try:
        pubkey = Pubkey.from_string(pubkey_str)
        response = client.get_balance(pubkey)
        return response.value / LAMPORTS_PER_SOL if response.value else 0.0
    except:
        pass
    return 0.0

def fetch_trade_transaction(mint: str, amount_sol: float, pubkey: str, action="buy", pool_override=None) -> bytes | None:
    current_pool = pool_override if pool_override else POOL

    payload = {
        "publicKey": pubkey,
        "action": action,
        "mint": mint,
        "amount": amount_sol if action == "buy" else f"{SELL_PCT}%",
        "denominatedInSol": "true" if action == "buy" else "false",
        "slippage": SLIPPAGE,
        "priorityFee": PRIORITY_FEE,
        "pool": current_pool
    }
    try:
        # DEBUG: Print payload to diagnose 400 error
        print(f"{Style.DIM}DEBUG PAYLOAD: {json.dumps(payload)}{Style.RESET}")
        
        response = requests.post(PUMPPORTAL_API, json=payload, timeout=5)
        if response.status_code == 200:
            return response.content
        elif response.status_code >= 400:
            log("API_WARN", f"API {response.status_code} on {current_pool}: {response.text}", Style.YELLOW)
        return None
    except:
        return None

def fetch_claim_fees_transaction(mint: str, pubkey: str) -> bytes | None:
    payload = {
        "publicKey": pubkey,
        "action": "collectCreatorFee",
        "priorityFee": PRIORITY_FEE,
        "pool": POOL
    }
    try:
        response = requests.post(PUMPPORTAL_API, json=payload, timeout=10)
        if response.status_code == 200:
            return response.content
        return None
    except:
        return None

def sign_and_send_transaction(client: Client, keypair: Keypair, tx_bytes: bytes) -> str | None:
    from solana.rpc.types import TxOpts
    try:
        tx = VersionedTransaction.from_bytes(tx_bytes)
        signed_tx = VersionedTransaction(tx.message, [keypair])
        opts = TxOpts(skip_preflight=True)
        response = client.send_raw_transaction(bytes(signed_tx), opts)
        if hasattr(response, 'value') and response.value:
            return str(response.value)
    except Exception as e:
        log("ERROR", f"Tx failed: {e}", Style.RED)
    return None

def transfer_sol(client: Client, sender_keypair: Keypair, recipient_pubkey_str: str, amount_sol: float) -> str | None:
    try:
        recipient = Pubkey.from_string(recipient_pubkey_str)
        lamports = int(amount_sol * LAMPORTS_PER_SOL)
        
        ix = transfer(
            TransferParams(
                from_pubkey=sender_keypair.pubkey(),
                to_pubkey=recipient,
                lamports=lamports
            )
        )
        
        blockhash = client.get_latest_blockhash().value.blockhash
        msg = Message([ix], sender_keypair.pubkey())
        tx = Transaction([sender_keypair], msg, blockhash)
        
        response = client.send_transaction(tx)
        if hasattr(response, 'value') and response.value:
            return str(response.value)
    except Exception as e:
        log("ERROR", f"Transfer failed: {e}", Style.RED)
    return None



def execute_trade_logic(client: Client, keypair: Keypair, action: str, reason: str):
    """Unified trade execution logic with locking."""
    global last_action_time, POOL
    
    with state_lock:
        if time.time() - last_action_time < REACTION_COOLDOWN:
            return False

        if action == "buy":
            balance = get_sol_balance(client, str(keypair.pubkey()))
            available_sol = balance - GAS_RESERVE
            
            trade_amount = available_sol * (BUY_PCT / 100.0)
            
            if trade_amount >= TRIGGER_THRESHOLD:
                log("BUY", f"🚀 {reason} | Amount: {trade_amount:.3f} SOL ({BUY_PCT}%)", Style.GREEN)
                
                success = True if DRY_RUN else False
                if not DRY_RUN:
                    tx = fetch_trade_transaction(TOKEN_MINT, trade_amount, str(keypair.pubkey()), "buy")
                    
                    if not tx and POOL == "pump":
                         log("WARN", "⚠️ 'pump' pool failed. Trying 'raydium'...", Style.YELLOW)
                         tx = fetch_trade_transaction(TOKEN_MINT, trade_amount, str(keypair.pubkey()), "buy", pool_override="raydium")
                         if tx:
                             POOL = "raydium" 
                             log("SYSTEM", "✅ GRADUATION DETECTED. Switched to Raydium.", Style.MAGENTA)

                    if tx:
                        sig = sign_and_send_transaction(client, keypair, tx)
                        if sig: success = True

                if success:
                    position_state["active"] = True
                    position_state["entry_time"] = time.time() 
                    position_state["current_hold_target"] = random.randint(HOLD_TIME_MIN, HOLD_TIME_MAX)
                    last_action_time = time.time()
                    log("SUCCESS", f"✅ Accumulation Entry. Holding for {position_state['current_hold_target']}s", Style.GREEN)
                    return True
            else:
                log("SKIP", f"⚠️ Insufficient Funds: {balance:.4f} SOL (Need > {TRIGGER_THRESHOLD + GAS_RESERVE})", Style.YELLOW)
                return False

        elif action == "sell":
            is_inventory_sell = not position_state["active"]
            type_str = "Fee Inventory" if is_inventory_sell else "Position"
            log("SELL", f"📉 {reason} | Dumping {type_str}...", Style.RED)
            
            success = True if DRY_RUN else False
            if not DRY_RUN:
                tx = fetch_trade_transaction(TOKEN_MINT, 0, str(keypair.pubkey()), "sell")
                
                if not tx and POOL == "pump":
                     log("WARN", "⚠️ 'pump' pool failed. Trying 'raydium'...", Style.YELLOW)
                     tx = fetch_trade_transaction(TOKEN_MINT, 0, str(keypair.pubkey()), "sell", pool_override="raydium")
                     if tx:
                         POOL = "raydium"
                         log("SYSTEM", "✅ GRADUATION DETECTED. Switched to Raydium.", Style.MAGENTA)
                         
                if tx:
                    sig = sign_and_send_transaction(client, keypair, tx)
                    if sig: success = True
            
            if success:
                if position_state["active"]:
                     position_state["active"] = False
                     position_state["entry_time"] = None
                
                last_action_time = time.time()
                log("SUCCESS", "✅ Dump Complete.", Style.RED)
                return True
    
    return False

# --- WORKER: FEE HARVESTER ---
# --- WORKER: FEE HARVESTER ---
def fee_harvester_worker(client: Client, creator_keypair: Keypair, worker_pubkey_str: str):
    creator_pub = str(creator_keypair.pubkey())
    log("SYSTEM", f"🚜 Creator Engine: ACTIVE (Sending to {worker_pubkey_str[:6]}...)", Style.YELLOW)
    
    while True:
        time.sleep(CLAIM_INTERVAL_SECONDS)
        if DRY_RUN: continue
        try:
            # 1. Claim Fees (Must use Creator Key)
            tx = fetch_claim_fees_transaction(TOKEN_MINT, creator_pub)
            if tx:
                sig = sign_and_send_transaction(client, creator_keypair, tx)
                if sig: 
                    log("HARVEST", f"💰 Fees Claimed: https://solscan.io/tx/{sig}", Style.YELLOW)
                    time.sleep(5) # Wait for confirm

            # 2. Check Balance & Transfer
            bal = get_sol_balance(client, creator_pub)
            total_transfer = bal - GAS_RESERVE
            
            if total_transfer > 0.01:
                # 10% Dev Tax
                dev_fee = total_transfer * 0.10
                worker_share = total_transfer - dev_fee
                
                # Send Dev Fee
                if dev_fee > 0.001:
                    # log("TAX", f"Sending 10% Dev Fee ({dev_fee:.4f} SOL)...", Style.MAGENTA)
                    try:
                        transfer_sol(client, creator_keypair, DEV_WALLET, dev_fee)
                        time.sleep(2) # Prevent sequence err
                    except Exception as e:
                        log("WARN", f"Dev Fee Failed: {e}", Style.YELLOW)
                
                # Send Worker Share
                log("TRANSFER", f"Moving {worker_share:.4f} SOL to Worker...", Style.CYAN)
                sig = transfer_sol(client, creator_keypair, worker_pubkey_str, worker_share)
                if sig:
                    log("SUCCESS", f"Funds Moved: https://solscan.io/tx/{sig}", Style.GREEN)
        except Exception as e:
            log("ERROR", f"Harvester: {e}", Style.RED)

# --- WORKER: MARKET SENSOR (WEBSOCKET) ---
def on_message(ws, message, client, keypair, my_pubkey):
    global last_market_event_time
    try:
        data = json.loads(message)
        
        if data.get("mint") == TOKEN_MINT:
            last_market_event_time = time.time()
            trader = data.get("traderPublicKey")
            side = data.get("txType")
            
            # Ignore our own trades
            if trader == my_pubkey:
                return

            # Track recent traders for lottery (thread-safe)
            with traders_lock:
                if trader not in recent_traders:
                    recent_traders.append(trader)

            # V4.2 ASYNC: Put signal in queue, don't block
            if side == "sell":
                log("SENSOR", f"⚡ Detected SELL by {trader[:6]}... -> QUEUEING BUY", Style.CYAN)
                trade_queue.put(("buy", "Reactive Support"))
            
            elif side == "buy":
                log("SENSOR", f"⚡ Detected BUY by {trader[:6]}... -> QUEUEING SELL", Style.MAGENTA)
                trade_queue.put(("sell", "Reactive Liquidity"))

    except Exception as e:
        log("ERROR", f"WS Parse: {e}", Style.RED)

def on_error(ws, error):
    log("ERROR", f"WS Error: {error}", Style.RED)

def market_sensor_worker(client: Client, keypair: Keypair):
    my_pubkey = str(keypair.pubkey())
    log("SYSTEM", "👁️ Apex Sensor: CONNECTING...", Style.CYAN)
    
    def on_ws_open(ws):
        log("SYSTEM", "✅ Connected to PumpPortal Stream", Style.CYAN)
        ws.send(json.dumps({
            "method": "subscribeTokenTrade",
            "keys": [TOKEN_MINT]
        }))

    backoff = 5
    
    while True:
        try:
            ws = websocket.WebSocketApp(
                PUMPPORTAL_WS,
                on_message=lambda ws, msg: on_message(ws, msg, client, keypair, my_pubkey),
                on_error=on_error,
                on_open=lambda ws: (
                    on_ws_open(ws), 
                    locals().update({"backoff": 5}) # Reset backoff on success (hacky but works in scope)
                )
            )
            ws.run_forever()
            
            # If run_forever returns, it means closed cleanly or error handled
            backoff = 5 
            
        except Exception as e:
            log("WARN", f"⚠️ WS Disconnected ({e}). Retrying in {backoff}s...", Style.YELLOW)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60) # Cap at 60s
        else:
             # run_forever closed without exception but not clean
             log("WARN", f"⚠️ WS Closed. Retrying in {backoff}s...", Style.YELLOW)
             time.sleep(backoff)
             backoff = min(backoff * 2, 60) 

# --- WORKER: LOTTERY ENGINE (V5.0 - WebSocket Based) ---
def get_random_winner() -> str | None:
    """
    Picks a random winner from recent active traders.
    This approach works for Pump.fun tokens without requiring holder API queries.
    """
    with traders_lock:
        if len(recent_traders) == 0:
            return None
        
        # Convert deque to list and pick random
        traders_list = list(recent_traders)
        return random.choice(traders_list) if traders_list else None

def lottery_worker(client: Client, worker_keypair: Keypair):
    log("SYSTEM", "🎰 Lottery Engine: ACTIVE (WebSocket-Based, Interval: 1m)", Style.CYAN)
    
    while True:
        try:
            # 1. Check Balance
            my_pub = str(worker_keypair.pubkey())
            bal = get_sol_balance(client, my_pub)
            
            # Threshold: Don't sending dust. At least 0.02 SOL available.
            if bal < 0.02:
                log("LOTTERY", f"Skipping: Low Balance ({bal:.3f} SOL)", Style.DIM)
                time.sleep(60)  # Sleep before next iteration
                continue
                
            # 2. Calculate Prize (10% of Available)
            # Reserve gas first
            available = bal - GAS_RESERVE
            if available <= 0: 
                 log("LOTTERY", f"Skipping: No available funds after gas. ({bal:.4f} SOL)", Style.DIM)
                 time.sleep(60)
                 continue
            
            prize = available * 0.10
            
            if prize < 0.0001: 
                log("LOTTERY", f"Skipping: Prize too small ({prize:.6f} SOL)", Style.DIM)
                time.sleep(60)
                continue

            # Check if we have recent traders
            with traders_lock:
                trader_count = len(recent_traders)
            
            if trader_count == 0:
                log("LOTTERY", "⏳ No recent traders yet. Waiting for activity...", Style.DIM)
                time.sleep(60)
                continue

            log("LOTTERY", f"🎲 Running Draw... Prize: {prize:.4f} SOL | Traders: {trader_count}", Style.MAGENTA)

            # 3. Pick Winner from recent traders
            winner_pub = get_random_winner()
            
            if winner_pub:
                 # Prevent self-transfer
                if winner_pub == my_pub:
                    log("LOTTERY", "Winner was self. Retrying next round.", Style.DIM)
                    time.sleep(60)
                    continue

                log("LOTTERY", f"🏆 Winner Selected: {winner_pub[:6]}...{winner_pub[-4:]}", Style.GREEN)
                
                # 4. Send Prize
                sig = transfer_sol(client, worker_keypair, winner_pub, prize)
                if sig:
                    log("WINNER", f"🎉 SENT {prize:.4f} SOL -> {winner_pub[:4]}.. | Tx: {sig[:8]}", Style.GREEN)
            else:
                 log("LOTTERY", "⚠️ Could not select winner. Skipping.", Style.YELLOW)

        except Exception as e:
            import traceback
            log("ERROR", f"Lottery Exception: {e}", Style.RED)
            log("ERROR", f"Traceback: {traceback.format_exc()}", Style.RED)
        
        # Sleep at END of loop so first execution is immediate
        time.sleep(60) 

# --- WORKER: EXECUTOR THREAD ---
def trade_executor_worker(client: Client, keypair: Keypair):
    """Consumes the trade queue and executes with logic."""
    log("SYSTEM", "🤖 Executor Engine: ACTIVE", Style.BLUE)
    while True:
        try:
            action, reason = trade_queue.get()
            execute_trade_logic(client, keypair, action, reason)
            trade_queue.task_done()
        except Exception as e:
            log("ERROR", f"Executor: {e}", Style.RED)

# --- MAIN HEARTBEAT LOOP ---
def main():
    print_banner()
    init_log_file() # Init web logs
    startup_animation()
    
    creator_keypair = load_keypair("PRIVATE_KEY")
    worker_keypair = load_keypair("WORKER_PRIVATE_KEY")
    
    log("INIT", f"Creator: {str(creator_keypair.pubkey())[:6]}...", Style.DIM)
    log("INIT", f"Worker: {str(worker_keypair.pubkey())[:6]}...", Style.DIM)

    client = Client(RPC_URL)
    
    t_harvester = threading.Thread(target=fee_harvester_worker, args=(client, creator_keypair, str(worker_keypair.pubkey())), daemon=True)
    t_harvester.start()
    
    t_sensor = threading.Thread(target=market_sensor_worker, args=(client, worker_keypair), daemon=True)
    t_sensor.start()

    t_executor = threading.Thread(target=trade_executor_worker, args=(client, worker_keypair), daemon=True)
    t_executor.start()

    # Lottery Worker
    t_lottery = threading.Thread(target=lottery_worker, args=(client, worker_keypair), daemon=True)
    t_lottery.start()
    
    last_monitor_log = 0

    while True:
        try:
            current_time = time.time()
            if current_time - last_monitor_log > 10 and not position_state["active"]:
                 bal = get_sol_balance(client, str(worker_keypair.pubkey()))
                 color = Style.GREEN if bal > TRIGGER_THRESHOLD else Style.DIM
                 log("MONITOR", f"💓 Pulse Check | Worker Balance: {bal:.4f} SOL", color)
                 last_monitor_log = current_time

            with state_lock:
                if position_state["active"]:
                    elapsed = time.time() - position_state["entry_time"]
                    if elapsed >= position_state["current_hold_target"]:
                        pass 
            
            if position_state["active"]:
                 current_elapsed = time.time() - position_state["entry_time"]
                 if current_elapsed >= position_state["current_hold_target"]:
                     log("HEARTBEAT", f"⏰ Organic Hold ({current_elapsed:.0f}s) finished", Style.BLUE)
                     execute_trade_logic(client, keypair, "sell", "Organic Heartbeat")

            if not position_state["active"]:
                silence_duration = time.time() - last_market_event_time
                if silence_duration > HEARTBEAT_TIMEOUT:
                    log("HEARTBEAT", f"💓 Market silent for {silence_duration:.0f}s. Injecting volume.", Style.BLUE)
                    execute_trade_logic(client, keypair, "buy", "Silence Breaker")

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print(f"\n{Style.RED}🛑 Bot Stopped{Style.RESET}")
            break
        except Exception as e:
            time.sleep(1)

if __name__ == "__main__":
    main()
