# security_monitoring.py - Simple Security Monitoring
import hashlib
import os
import logging
import time
from pathlib import Path
from datetime import datetime

class SecurityMonitor:
    """Simple security monitoring for trading system"""
    
    def __init__(self):
        self.critical_files = [
            'config.json.encrypted', 'secret.key', 'main.py'
        ]
        self.baseline_hashes = {}
        self.security_log_file = "security_events.log"
        
        # Create security log if it doesn't exist
        if not Path(self.security_log_file).exists():
            with open(self.security_log_file, 'w') as f:
                f.write(f"Security Log Started - {datetime.now()}\n")
        
        # Create baseline hashes
        for file_path in self.critical_files:
            if Path(file_path).exists():
                self.baseline_hashes[file_path] = self._get_file_hash(file_path)
    
    def _get_file_hash(self, filepath):
        """Get SHA256 hash of a file"""
        if not Path(filepath).exists():
            return None
        
        try:
            sha256_hash = hashlib.sha256()
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(chunk)
            return sha256_hash.hexdigest()
        except Exception as e:
            logging.error(f"Error calculating hash for {filepath}: {e}")
            return None
    
    def check_file_integrity(self):
        """Check if critical files have been modified"""
        try:
            for file_path in self.critical_files:
                if Path(file_path).exists():
                    current_hash = self._get_file_hash(file_path)
                    if file_path in self.baseline_hashes:
                        if current_hash != self.baseline_hashes[file_path]:
                            self.log_connection_event("FILE_MODIFIED", f"{file_path} has been changed")
                            self.baseline_hashes[file_path] = current_hash
        except Exception as e:
            logging.error(f"Error checking file integrity: {e}")
    
    def check_unauthorized_access(self):
        """Check for signs of unauthorized access"""
        try:
            # Simple check - look for new executable files
            suspicious_files = list(Path(".").glob("*.exe"))
            for file in suspicious_files:
                if file.name not in ["terminal64.exe"]:  # Allow MT5
                    self.log_connection_event("SUSPICIOUS_FILE", f"Found executable: {file.name}")
        except Exception as e:
            logging.error(f"Error checking unauthorized access: {e}")
    
    def log_connection_event(self, event_type, details=""):
        """Log security-relevant connection events"""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = f"[{timestamp}] {event_type}: {details}"
            
            # Log to main logger
            logging.info(f"🔐 SECURITY: {event_type} - {details}")
            
            # Write to security log file
            with open(self.security_log_file, "a", encoding='utf-8') as f:
                f.write(log_entry + "\n")
                
        except Exception as e:
            logging.error(f"Error logging security event: {e}")