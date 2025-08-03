# secure_config.py - SIMPLE VERSION
import os
import json
from cryptography.fernet import Fernet

def make_config_secure():
    print("🔐 Making your config secure...")
    
    # Create encryption key
    key = Fernet.generate_key()
    
    # Save the key
    with open('secret.key', 'wb') as f:
        f.write(key)
    
    # Load your config
    with open('config.json', 'r') as f:
        config = json.load(f)
    
    # Encrypt it
    cipher = Fernet(key)
    encrypted = cipher.encrypt(json.dumps(config).encode())
    
    # Save encrypted config
    with open('config.json.encrypted', 'wb') as f:
        f.write(encrypted)
    
    print("✅ Done! Your config is now secure!")

def load_secure_config():
    # Load key
    with open('secret.key', 'rb') as f:
        key = f.read()
    
    # Load encrypted config
    with open('config.json.encrypted', 'rb') as f:
        encrypted = f.read()
    
    # Decrypt and return
    cipher = Fernet(key)
    decrypted = cipher.decrypt(encrypted)
    return json.loads(decrypted)

if __name__ == "__main__":
    make_config_secure()