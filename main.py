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

# --- WORKER: LOTTERY ENGINE (V5.0) ---
def get_random_holder(client: Client, mint: str) -> str | None:
    """
    Fetches holders for the mint and picks a random winner.
    Tries SolanaTracker API first (fast), falls back to RPC (slow/heavy).
    """
    exclude = [
        "11111111111111111111111111111111", # System
        "Dead111111111111111111111111111111111111", # Burn
        TOKEN_MINT # Token Account
    ]

    # 1. Try Helius / RPC Directly (Preferred for Accuracy)
    helius_key = os.getenv("HELIUS_API_KEY")
    if helius_key:
        log("LOTTERY", f"✓ Helius API Key Detected (First 4: {helius_key[:4]}...)", Style.CYAN)
        try:
            # Correct Helius RPC endpoint format
            url = f"https://mainnet.helius-rpc.com/?api-key={helius_key}"
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getProgramAccounts",
                "params": [
                    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", # SPL Token Program
                    {
                        "encoding": "jsonParsed",
                        "filters": [
                            {"dataSize": 165},
                            {"memcmp": {"offset": 0, "bytes": mint}}
                        ]
                    }
                ]
            }
            log("LOTTERY", "→ Fetching holders via Helius RPC...", Style.DIM)
            res = requests.post(url, json=payload, timeout=15)
            
            if res.status_code == 200:
                data = res.json()
                
                # Check for JSON-RPC error response
                if "error" in data:
                    log("WARN", f"Helius RPC Error: {data['error']}", Style.YELLOW)
                else:
                    accounts = data.get("result", [])
                    log("LOTTERY", f"✓ Helius returned {len(accounts)} token accounts", Style.CYAN)
                    
                    valid_holders = []
                    for acc in accounts:
                        try:
                            info = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
                            owner = info.get("owner")
                            amount = float(info.get("tokenAmount", {}).get("uiAmount", 0))
                            
                            if owner and owner not in exclude and amount > 0:
                                valid_holders.append(owner)
                        except: continue

                    if valid_holders:
                        log("LOTTERY", f"✓ Found {len(valid_holders)} valid holders via Helius", Style.GREEN)
                        return random.choice(valid_holders)
                    else:
                        log("LOTTERY", "No valid holders after filtering (Helius)", Style.YELLOW)
            else:
                 log("WARN", f"Helius HTTP Error: {res.status_code} - {res.text[:200]}", Style.YELLOW)

        except Exception as e:
             log("WARN", f"Helius Request Failed: {str(e)}", Style.YELLOW)
    else:
        log("LOTTERY", "⚠️ HELIUS_API_KEY not found in environment", Style.YELLOW)

    # 2. Try SolanaTracker API (Fallback)
    api_key = os.getenv("SOLANATRACKER_API_KEY")
    if api_key:
        try:
            url = f"https://data.solanatracker.io/tokens/{mint}/holders"
            headers = {"x-api-key": api_key}
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                holders = data if isinstance(data, list) else data.get("holders", [])
                valid_holders = [h for h in holders if h.get("wallet") not in exclude and float(h.get("amount", 0)) > 0]
                if valid_holders:
                    winner = random.choice(valid_holders)
                    return winner.get("wallet")
            else:
                 log("WARN", f"Tracker API Error: {res.status_code}", Style.YELLOW)
        except Exception as e:
            log("WARN", f"Tracker API Failed: {e}", Style.YELLOW)

    return None

def lottery_worker(client: Client, worker_keypair: Keypair):
    log("SYSTEM", "🎰 Lottery Engine: ACTIVE (Interval: 1m DEBUG)", Style.CYAN)
    
    while True:
        # Sleep 1 minute (DEBUG MODE)
        time.sleep(60)
        
        try:
            # 1. Check Balance
            my_pub = str(worker_keypair.pubkey())
            bal = get_sol_balance(client, my_pub)
            
            # Threshold: Don't sending dust. At least 0.02 SOL available.
            if bal < 0.02:
                log("LOTTERY", f"Skipping: Low Balance ({bal:.3f} SOL)", Style.DIM)
                continue
                
            # 2. Calculate Prize (10% of Available)
            # Reserve gas first
            available = bal - GAS_RESERVE
            if available <= 0: 
                 log("LOTTERY", f"Skipping: No available funds after gas. ({bal:.4f} SOL)", Style.DIM)
                 continue
            
            prize = available * 0.10
            
            if prize < 0.0001: 
                log("LOTTERY", f"Skipping: Prize too small ({prize:.6f} SOL)", Style.DIM)
                continue

            log("LOTTERY", f"🎲 Running Draw... Prize: {prize:.4f} SOL", Style.MAGENTA)

            # 3. Pick Winner
            winner_pub = get_random_holder(client, TOKEN_MINT)
            
            if winner_pub:
                 # Prevent self-transfer
                if winner_pub == my_pub:
                    log("LOTTERY", "Winner was self. Retrying next round.", Style.DIM)
                    continue

                log("LOTTERY", f"🏆 Winner Selected: {winner_pub[:6]}...{winner_pub[-4:]}", Style.GREEN)
                
                # 4. Send Prize
                sig = transfer_sol(client, worker_keypair, winner_pub, prize)
                if sig:
                    log("WINNER", f"🎉 SENT {prize:.4f} SOL -> {winner_pub[:4]}.. | Tx: {sig[:8]}", Style.GREEN)
            else:
                 log("LOTTERY", "⚠️ Could not fetch holders. Skipping.", Style.YELLOW)

        except Exception as e:
            log("ERROR", f"Lottery: {e}", Style.RED) 

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
