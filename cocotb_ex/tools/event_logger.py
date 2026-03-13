import json
import time
import hashlib
import os
import sys
from datetime import datetime

class EventLogger:
    def __init__(self, role, log_file=None):
        self.role = role
        self.log_file = log_file or os.environ.get("OPENCHIPFLOW_EVENT_LOG", "event_log.jsonl")
        self.start_time = None

    def _get_hash(self, file_path):
        if not file_path or not os.path.exists(file_path):
            return None
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            while True:
                data = f.read(65536)
                if not data:
                    break
                sha256.update(data)
        return sha256.hexdigest()

    def start(self, inputs=None):
        self.start_time = time.time()
        input_hashes = {}
        if inputs:
            for k, v in inputs.items():
                input_hashes[k] = self._get_hash(v)
        
        event = {
            "role": self.role,
            "event_type": "start",
            "timestamp": self.start_time,
            "iso_time": datetime.now().isoformat(),
            "inputs": inputs,
            "input_hashes": input_hashes
        }
        self._write_event(event)

    def end(self, exit_code, outputs=None):
        end_time = time.time()
        duration = end_time - (self.start_time or end_time)
        output_hashes = {}
        if outputs:
            for k, v in outputs.items():
                output_hashes[k] = self._get_hash(v)

        event = {
            "role": self.role,
            "event_type": "end",
            "timestamp": end_time,
            "iso_time": datetime.now().isoformat(),
            "exit_code": exit_code,
            "duration": duration,
            "outputs": outputs,
            "output_hashes": output_hashes
        }
        self._write_event(event)

    def _write_event(self, event):
        try:
            with open(self.log_file, "a") as f:
                f.write(json.dumps(event) + "\n")
        except Exception as e:
            sys.stderr.write(f"Failed to write event log: {e}\n")

if __name__ == "__main__":
    # Simple CLI for shell scripts
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True)
    parser.add_argument("--event", choices=["start", "end"], required=True)
    parser.add_argument("--inputs", nargs="*", help="key=path pairs")
    parser.add_argument("--outputs", nargs="*", help="key=path pairs")
    parser.add_argument("--exit-code", type=int, default=0)
    parser.add_argument("--start-time", type=float, help="Start time timestamp for end event duration calculation")
    
    args = parser.parse_args()
    
    logger = EventLogger(args.role)
    
    def parse_kv(items):
        d = {}
        if items:
            for item in items:
                if "=" in item:
                    k, v = item.split("=", 1)
                    d[k] = v
        return d

    if args.event == "start":
        logger.start(parse_kv(args.inputs))
        # Print the timestamp so the shell script can capture it
        print(logger.start_time)
    elif args.event == "end":
        if args.start_time:
            logger.start_time = args.start_time
        else:
            logger.start_time = time.time() # fallback
            
        logger.end(args.exit_code, parse_kv(args.outputs))
