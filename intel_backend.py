import asyncio
import websockets
import os, glob, time, re, json, copy
from collections import deque
import tkinter as tk
from tkinter import filedialog, messagebox

# --- CONFIGURATION LOADER ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "intel_config.json")
MAP_DATA_FILE = os.path.join(BASE_DIR, "eve_map_data.json")

def load_cfg():
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}

def save_cfg(config_data):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=4)
        return True
    except IOError:
        return False

def get_log_dir_from_user():
    """
    Uses Tkinter to show a folder selection dialog to the user.
    Asks for the 'Chatlogs' directory and returns its parent ('logs').
    """
    root = tk.Tk()
    root.withdraw()  # Hide the main Tkinter window

    messagebox.showinfo(
        "EVE Intel Setup",
        "Please select your EVE Online 'Chatlogs' directory.\n\n"
        "This is typically found inside your 'Documents/EVE/logs/' folder."
    )

    # askdirectory returns the path to the selected directory
    selected_dir = filedialog.askdirectory(title="Select EVE 'Chatlogs' Directory")

    if not selected_dir:
        messagebox.showerror("Setup Cancelled", "No directory was selected. The application cannot continue.")
        return None

    # We need to check if the selected directory is actually named 'Chatlogs'
    if os.path.basename(os.path.normpath(selected_dir)).lower() != 'chatlogs':
        messagebox.showwarning(
            "Directory Invalid",
            f"The folder you selected is not named 'Chatlogs'.\n\n"
            f"You selected: {selected_dir}\n\n"
            "Please find and select the 'Chatlogs' directory itself."
        )
        return None
    
    # The user has selected the Chatlogs directory. We need to save its PARENT to the config.
    # The rest of the script expects the 'root_log_dir' to be the parent of 'Chatlogs'.
    parent_dir = os.path.dirname(selected_dir)
    return parent_dir


cfg = load_cfg()

# --- Path Validation and User Prompting ---
def find_and_validate_log_dir(current_cfg):
    # 1. Try the configured path first
    config_path = current_cfg.get("eve_log_root")
    if config_path and os.path.isdir(os.path.join(config_path, "Chatlogs")):
        print(f"[*] Using configured log directory: {config_path}")
        return config_path

    # 2. If config is bad/missing, try the default location
    default_log_parent = os.path.normpath(os.path.expanduser("~/Documents/EVE/logs"))
    if os.path.isdir(os.path.join(default_log_parent, "Chatlogs")):
        print(f"[*] Found EVE log directory at default location: {default_log_parent}")
        current_cfg['eve_log_root'] = default_log_parent
        save_cfg(current_cfg)
        return default_log_parent

    # 3. If all else fails, prompt the user
    print("[*] EVE log directory not configured or is invalid. Prompting user for location...")
    new_log_dir_parent = get_log_dir_from_user()
    
    if new_log_dir_parent:
        current_cfg["eve_log_root"] = new_log_dir_parent
        save_cfg(current_cfg)
        return new_log_dir_parent
    
    # 4. If user cancels, we can't continue
    messagebox.showerror("Setup Failed", "A valid EVE log directory is required to run. Exiting.")
    print("[!] No valid log directory provided. Exiting.")
    exit()

# Get the validated log directory path
root_log_dir = find_and_validate_log_dir(cfg)
EVE_LOG_DIR = os.path.normpath(os.path.join(root_log_dir, "Chatlogs"))

ALERT_DURATION = 180

try:
    with open(MAP_DATA_FILE, 'r', encoding='utf-8') as f:
        map_data = json.load(f)
    RAW_CONNECTIONS = map_data.get("RAW_CONNECTIONS", [])
    JUMP_BRIDGES = map_data.get("JUMP_BRIDGES", [])
    STOP_WORDS_LIST = map_data.get("STOP_WORDS", [])
except (FileNotFoundError, json.JSONDecodeError) as e:
    print(f"[!] CRITICAL: Could not load map data from {MAP_DATA_FILE}. Error: {e}")
    RAW_CONNECTIONS = []
    JUMP_BRIDGES = []
    STOP_WORDS_LIST = []

def get_initial_system():
    """
    Finds the latest EVE local chat log and parses the last known system from it.
    """
    try:
        if not os.path.exists(EVE_LOG_DIR):
            print(f"[!] Log directory not found: {EVE_LOG_DIR}")
            return None

        list_of_files = glob.glob(os.path.join(EVE_LOG_DIR, 'Local_*.txt'))
        if not list_of_files:
            print(f"[*] No EVE 'Local' chat logs found in: {EVE_LOG_DIR}")
            return None

        latest_file = max(list_of_files, key=os.path.getctime)
        print(f"[*] Reading initial system from: {os.path.basename(latest_file)}")

        system_change_regex = re.compile(r"Channel changed to Local\s*:\s*([\w\- ]+)", re.IGNORECASE)
        
        current_system = None
        # EVE logs are UTF-16, so we read with that encoding directly.
        try:
            with open(latest_file, 'r', encoding='utf-16', errors='ignore') as f:
                for line in f:
                    clean_line = line.strip().replace('\ufeff', '')
                    match = system_change_regex.search(clean_line)
                    if match:
                        current_system = match.group(1).strip()
        except Exception as e:
            print(f"[!] Error reading initial system file with utf-16: {e}")
        
        if current_system:
            print(f"[*] Determined initial system from log file: {current_system}")
        else:
            print("[*] Could not determine initial system from the latest log file.")
        return current_system
    except Exception as e:
        print(f"[!] Error reading chat log for initial system: {e}")
        return None

class BackendMonitor:
    def __init__(self):
        self.active_alerts = {}
        self.jb_enabled = False 
        self.base_graph = self.build_graph(RAW_CONNECTIONS)
        self.jb_graph = self.build_graph(RAW_CONNECTIONS + JUMP_BRIDGES)
        
        self.alert_distances = {} 
        self.ui_distances = {}    
        
        base_systems = set()
        for u, v in RAW_CONNECTIONS:
            base_systems.add(u)
            base_systems.add(v)
            
        self.systems = sorted(list(base_systems), key=len, reverse=True)
        self.abbrevs = self.gen_abbrevs(self.systems)
        
        self.pilot_locations = {}
        self.stop_words = set(STOP_WORDS_LIST)

        self.intel_file = None
        self.intel_pos = 0
        self.local_chat_file = None
        self.local_chat_pos = 0
        
        initial_system = get_initial_system()
        self.home_system = initial_system or cfg.get("home_system", "00GD-D")
        self.rebuild_and_recalc()
        
        self.pattern = re.compile(r"^(\[.*?\])\s*(.*?)>\s*(.*)$")
        self.local_jump_pattern = re.compile(r"Channel changed to Local\s*:\s*([\w\- ]+)", re.IGNORECASE)
        self.connected_clients = set()

        self.ship_data = {}
        self.ship_names = set()
        self.ship_names_sorted = []
        self.ship_name_aliases = {}
        ship_file = os.path.join(BASE_DIR, "eve_ships_combat_profiles.json")
        try:
            with open(ship_file, 'r', encoding='utf-8') as f:
                ship_list = json.load(f)
                # First pass: collect all names and basic data
                for ship in ship_list:
                    ship_name_upper = ship['name'].upper()
                    self.ship_names.add(ship_name_upper)
                    self.ship_data[ship_name_upper] = ship
                
                # Second pass: determine base hull name for image mapping
                all_ship_names = set(self.ship_data.keys())
                for ship_name in all_ship_names:
                    # Find potential base hulls by checking for prefixes
                    bases = [b for b in all_ship_names if ship_name.startswith(b + ' ') and b != ship_name]
                    if bases:
                        # The best base is the longest prefix match
                        self.ship_data[ship_name]['hull_name'] = max(bases, key=len)
                    else:
                        # No prefix found, it's its own base hull
                        self.ship_data[ship_name]['hull_name'] = ship_name
                
                # Third pass: Create aliases from last word of multi-word names
                alias_stop_words = {'ISSUE', 'EDITION', 'NAVY', 'FLEET', 'IMPERIAL', 'REPUBLIC', 'FEDERATION', 'GURISTAS', 'SERPENTIS'}
                for ship_name in all_ship_names:
                    words = ship_name.split()
                    if len(words) > 1:
                        last_word = words[-1]
                        # Add alias if it's not a stop word, is long enough, and isn't already a full ship name or existing alias
                        if last_word not in alias_stop_words and len(last_word) > 3:
                             if last_word not in all_ship_names and last_word not in self.ship_name_aliases:
                                 self.ship_name_aliases[last_word] = ship_name
                
                # Add aliases to the set of names to search for
                self.ship_names.update(self.ship_name_aliases.keys())
                self.ship_names_sorted = sorted(list(self.ship_names), key=len, reverse=True)
                print(f"[*] Successfully loaded data for {len(self.ship_data)} ships and {len(self.ship_name_aliases)} aliases.")
        except FileNotFoundError:
            print(f"[!] CRITICAL: '{ship_file}' not found. Ship detection will not work.")
            self.ship_names = set()
            self.ship_names_sorted = []
            self.ship_name_aliases = {}
            self.ship_data = {}
        except json.JSONDecodeError:
            print(f"[!] CRITICAL: Failed to parse '{ship_file}'. It might be malformed. Ship detection will not work.")
        except Exception as e:
            print(f"[!] CRITICAL: An unexpected error occurred while loading '{ship_file}': {e}")

    def build_graph(self, conns):
        g = {}
        for u, v in conns:
            for x, y in [(u, v), (v, u)]:
                if x not in g: g[x] = []
                if y not in g[x]: g[x].append(y)
        return g

    def gen_abbrevs(self, syslist):
        m = {}
        for s in syslist:
            for i in range(3, len(s) + 1):
                pref = s[:i].upper()
                if not any(o != s and o.upper().startswith(pref) for o in syslist): m[pref] = s
        return m

    def bfs_distances(self, graph, start):
        dists = {start: 0}
        q = deque([start])
        while q:
            curr = q.popleft()
            for n in graph.get(curr, []):
                if n not in dists: 
                    dists[n] = dists[curr] + 1
                    q.append(n)
        return dists

    def rebuild_and_recalc(self):
        self.alert_distances = self.bfs_distances(self.base_graph, self.home_system)
        if self.jb_enabled:
            self.ui_distances = self.bfs_distances(self.jb_graph, self.home_system)
        else:
            self.ui_distances = self.alert_distances

    def read_file_safely(self, path, last_pos):
        try:
            # Always use binary mode for reading and seeking to ensure byte-level precision.
            with open(path, 'rb') as f:
                # Check if file was truncated or replaced
                f.seek(0, 2)
                if last_pos > f.tell():
                    last_pos = 0
                
                f.seek(last_pos)
                new_bytes = f.read()
                new_pos = f.tell()

            if not new_bytes:
                return [], last_pos
            
            decoded_text = new_bytes.decode('utf-16', errors='replace')
            
            return decoded_text.splitlines(), new_pos
        except FileNotFoundError:
            return [], last_pos
        except Exception as e:
            print(f"[!] Error in read_file_safely for {path}: {e}")
            return [], last_pos

    async def broadcast_state(self):
        if not self.connected_clients:
            return

        # Create a serializable copy of the alerts, converting sets to lists
        serializable_alerts = copy.deepcopy(self.active_alerts)
        for alert_data in serializable_alerts.values():
            if 'pilots' in alert_data and isinstance(alert_data['pilots'], set):
                alert_data['pilots'] = list(alert_data['pilots'])

        payload = json.dumps({
            "type": "alert_update",
            "alerts": serializable_alerts,
            "home_system": self.home_system,
            "distances": self.ui_distances  
        })
        await asyncio.gather(*(client.send(payload) for client in self.connected_clients), return_exceptions=True)

    async def check_timers(self):
        now = time.time()
        expired = [k for k, v in self.active_alerts.items() if now > v["expiry"]]
        for k in expired: 
            del self.active_alerts[k]
        if expired:
            await self.broadcast_state()

    async def run(self):
        print(f"[*] Backend targeting log folder: {EVE_LOG_DIR}")
        while True:
            try:
                all_txt = glob.glob(os.path.join(EVE_LOG_DIR, "*.txt"))
                files = [f for f in all_txt if "intel" in os.path.basename(f).lower() or "ftn" in os.path.basename(f).lower()]
                
                latest_intel = max(files, key=os.path.getmtime) if files else None
                
                if latest_intel:
                    if latest_intel != self.intel_file:
                        self.intel_file = latest_intel
                        with open(latest_intel, 'rb') as f:
                            f.seek(0, 2)
                            self.intel_pos = f.tell()
                        print(f"[*] Connected to Intel file: {os.path.basename(latest_intel)}")

                    lines, self.intel_pos = self.read_file_safely(latest_intel, self.intel_pos)
                    
                    state_changed = False
                    for l in lines:
                        m = self.pattern.search(l.replace('\x00', '').strip())
                        if m:
                            ts, rep, body = m.groups()
                            bup = body.upper()

                            # Format the timestamp for UI display, keeping only the time part.
                            time_str = ts
                            try:
                                time_match = re.search(r'(\d{2}:\d{2}:\d{2})', ts)
                                if time_match:
                                    time_str = f"[{time_match.group(1)}]"
                            except Exception: pass # Fallback to original ts
                            
                            # Expand common ship abbreviations to their full names for better matching.
                            abbreviations = {
                                r'\bNI\b': 'NAVY ISSUE',
                                r'\bFI\b': 'FLEET ISSUE',
                                r'\bNAVY\b(?!\s+ISSUE)': 'NAVY ISSUE',
                                r'\bFLEET\b(?!\s+ISSUE)': 'FLEET ISSUE',
                            }
                            for abbr, full_text in abbreviations.items():
                                bup = re.sub(abbr, full_text, bup)
                            
                            # --- SHIP DETECTION ---
                            ships_in_line_raw = []
                            remaining_body = bup
                            for ship in self.ship_names_sorted:
                                # Find all occurrences of the ship name as a whole word/phrase
                                pattern = r'\b' + re.escape(ship) + r'\b'
                                matches = re.findall(pattern, remaining_body)
                                if matches:
                                    ships_in_line_raw.extend(matches)
                                    # Remove the found ship name to prevent partial matches later
                                    remaining_body = re.sub(pattern, '', remaining_body)
                            
                            # Map aliases back to full names for internal logic
                            ships_in_line = [self.ship_name_aliases.get(s, s) for s in ships_in_line_raw]

                            ship_counts = {}
                            for s in ships_in_line:
                                ship_counts[s] = ship_counts.get(s, 0) + 1

                            # --- CLICKABLE HTML GENERATION ---
                            ui_body_html = body
                            if ships_in_line_raw:
                                # Get a unique list of the search terms that were actually found in the text
                                unique_search_terms = sorted(list(set(ships_in_line_raw)), key=len, reverse=True)

                                # Create a regex that matches any of the unique search terms
                                regex_group = '|'.join(re.escape(s) for s in unique_search_terms)
                                pattern = f'({regex_group})'
                                
                                # Split the original body string, keeping the delimiters
                                parts = re.split(pattern, body, flags=re.IGNORECASE)
                                
                                new_html_parts = []
                                for part in parts:
                                    part_upper = part.upper()
                                    if part_upper in unique_search_terms:
                                        full_ship_name = self.ship_name_aliases.get(part_upper, part_upper)
                                        ship_js = full_ship_name.replace("'", "\\'")
                                        span = f'<span class="ship-tag" onclick="showShipInfo(\'{ship_js}\')">{part}</span>'
                                        new_html_parts.append(span)
                                    else:
                                        new_html_parts.append(part)
                                ui_body_html = "".join(new_html_parts)

                            if self.connected_clients:
                                log_payload = json.dumps({"type": "log_line", "time": time_str, "text": f"{rep} > {ui_body_html}"})
                                await asyncio.gather(*(client.send(log_payload) for client in self.connected_clients), return_exceptions=True)

                            found = [s for s in self.systems if re.search(r'(?<!\w)' + re.escape(s) + r'(?!\w)', bup)]
                            if not found:
                                for t in re.split(r'[^A-Z0-9\-]', bup):
                                    if t in self.abbrevs: found.append(self.abbrevs[t])
                            
                            found = list(set(found))
                            d_min, primary = 999, None                            
                            for s in found:
                                d = self.alert_distances.get(s, 999)
                                if d < d_min: 
                                    d_min, primary = d, s
                                
                            is_clear_msg = any(x in bup for x in ["CLR", "CLEAR"]) or "KILL:" in bup
                            is_status_msg = "STATUS" in bup
                            parsed_pilots = []

                            if primary and not is_clear_msg and not is_status_msg:
                                text_for_pilots = body
                                text_for_pilots = re.sub(r'\b' + re.escape(primary) + r'\b', '', text_for_pilots, flags=re.IGNORECASE)
                                
                                potential_names = re.findall(r'\b[A-Z][a-zA-Z0-9\'-]*(?:\s[A-Z][a-zA-Z0-9\'-]*)*\b', text_for_pilots)
                                
                                for name in potential_names:
                                    upper_name = name.upper()
                                    if upper_name in self.ship_names or upper_name in self.stop_words or len(upper_name.strip()) <= 1:
                                        continue
                                    if any(part.upper() in self.stop_words for part in name.split()):
                                        continue
                                    parsed_pilots.append(name.strip())

                            if parsed_pilots and primary:
                                for pilot in parsed_pilots:
                                    previous_system = self.pilot_locations.get(pilot)
                                    if previous_system and previous_system != primary:
                                        if previous_system in self.active_alerts and 'pilots' in self.active_alerts[previous_system]:
                                            self.active_alerts[previous_system]['pilots'].discard(pilot)
                                            
                                            if not self.active_alerts[previous_system]['pilots']:
                                                print(f"[*] Clearing alert for {previous_system} as tracked pilots have moved.")
                                                self.active_alerts[previous_system]['cleared'] = True
                                                state_changed = True
                                    self.pilot_locations[pilot] = primary
                            
                            cnt_m = re.search(r'(\+\d+|\d+\+)', body)
                            cnt_val = cnt_m.group(1) if cnt_m else ""
                            is_spike = bool(re.search(r'\bSPIKE\b', bup))

                            if primary:
                                now = time.time()
                                if is_clear_msg:
                                    if primary in self.active_alerts:
                                        self.active_alerts[primary]["cleared"] = True
                                        state_changed = True
                                elif not is_status_msg:
                                    if primary not in self.active_alerts or self.active_alerts[primary].get('cleared', False):
                                        self.active_alerts[primary] = {
                                            "expiry": now + ALERT_DURATION, "dist": d_min, "cleared": False,
                                            "count": cnt_val, "is_spike": is_spike,
                                            "trigger_intel": f"{time_str} {rep} > {body}",
                                            "ships": ship_counts, "pilots": set(parsed_pilots)
                                        }
                                    else:
                                        alert = self.active_alerts[primary]
                                        alert['expiry'] = now + ALERT_DURATION
                                        alert['is_spike'] = alert['is_spike'] or is_spike
                                        alert['trigger_intel'] = f"{time_str} {rep} > {body}"
                                        if cnt_val: alert['count'] = cnt_val
                                        alert.setdefault('pilots', set()).update(parsed_pilots)
                                    state_changed = True

                    if state_changed:
                        for sys_name in self.active_alerts:
                            self.active_alerts[sys_name]["dist"] = self.alert_distances.get(sys_name, 999)
                        await self.broadcast_state()

                loc_files = glob.glob(os.path.join(EVE_LOG_DIR, "Local_*.txt"))
                latest_local = max(loc_files, key=os.path.getmtime) if loc_files else None
                
                if latest_local:
                    if latest_local != self.local_chat_file:
                        self.local_chat_file = latest_local
                        with open(latest_local, 'rb') as f:
                            f.seek(0, 2)
                            self.local_chat_pos = f.tell()
                            
                    loc_lines, self.local_chat_pos = self.read_file_safely(latest_local, self.local_chat_pos)
                    for ll in loc_lines:
                        clean_line = ll.strip().replace('\ufeff', '').replace('\x00', '')
                        jm = self.local_jump_pattern.search(clean_line)
                        if jm:
                            new_sys = jm.group(1).strip()
                            if new_sys in self.systems and new_sys != self.home_system:
                                self.home_system = new_sys
                                self.rebuild_and_recalc()
                                
                                for sys_name in self.active_alerts:
                                    self.active_alerts[sys_name]["dist"] = self.alert_distances.get(sys_name, 999)
                                
                                await self.broadcast_state()
                                
                                if self.connected_clients:
                                    jump_payload = json.dumps({"type": "system_jump", "system": new_sys})
                                    await asyncio.gather(*(client.send(jump_payload) for client in self.connected_clients), return_exceptions=True)

                await self.check_timers()
            except Exception as e:
                print(f"Error: {e}")
            
            await asyncio.sleep(1)

monitor = BackendMonitor()

async def ws_handler(websocket, *args, **kwargs):
    print(f"[*] Browser connected! Address: {websocket.remote_address}")
    monitor.connected_clients.add(websocket)
    try:
        await websocket.send(json.dumps({"type": "init_ship_data", "data": monitor.ship_data}))
        await monitor.broadcast_state()
        
        async for message in websocket:
            try:
                data = json.loads(message)
                if data.get("type") == "set_home":
                    monitor.home_system = data["system"]
                    monitor.rebuild_and_recalc()
                    for sys_name in monitor.active_alerts:
                        monitor.active_alerts[sys_name]["dist"] = monitor.alert_distances.get(sys_name, 999)
                    await monitor.broadcast_state()
                    
                elif data.get("type") == "toggle_jb":
                    monitor.jb_enabled = data["enabled"]
                    monitor.rebuild_and_recalc()
                    for sys_name in monitor.active_alerts:
                        monitor.active_alerts[sys_name]["dist"] = monitor.alert_distances.get(sys_name, 999)
                    await monitor.broadcast_state()
            except Exception as e:
                print(f"[!] Error processing browser message: {e}")
                
    except websockets.exceptions.ConnectionClosed as e:
        print(f"[*] Browser disconnected. Reason: {e}")
    except Exception as e:
        print(f"[!] Unexpected WebSocket error: {e}")
    finally:
        monitor.connected_clients.remove(websocket)

async def main():
    print("[*] Starting EVE WebSocket server on 127.0.0.1:8000...")
    asyncio.create_task(monitor.run())
    try:
        async with websockets.serve(ws_handler, "127.0.0.1", 8000):
            print("[*] =====================================================")
            print("[*] SERVER ONLINE: Web Dashboard ready to connect")
            print("[*] Waiting for browser connection...")
            print("[*] =====================================================")
            await asyncio.Future()
    except OSError as e:
        print(f"[!] ERROR: Could not start server on port 8000. Is it already in use? ({e})")

if __name__ == "__main__":
    asyncio.run(main())
