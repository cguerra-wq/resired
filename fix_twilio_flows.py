import json
import glob
import os

def fix_flow(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    for state in data.get('states', []):
        if state['type'] == 'trigger':
            next_step = None
            for t in state['transitions']:
                if (t['event'] in ['incomingRequest', 'incomingMessage']) and t['next'] is not None:
                    next_step = t['next']
            
            state['transitions'] = [
                { "event": "incomingMessage", "next": next_step if "router" in data.get('description', '').lower() else None },
                { "event": "incomingCall", "next": None },
                { "event": "incomingConversationMessage", "next": None },
                { "event": "incomingRequest", "next": next_step if "router" not in data.get('description', '').lower() else None },
                { "event": "incomingParent", "next": None }
            ]
            
        elif state['type'] == 'make-http-request':
            for t in state['transitions']:
                if t['event'] == 'fail':
                    t['event'] = 'failed'
            
            if 'timeout' in state.get('properties', {}):
                del state['properties']['timeout']
                
        elif state['type'] in ['send-message', 'send-and-wait-for-reply']:
            has_failed = any(t['event'] == 'failed' for t in state['transitions'])
            if not has_failed:
                state['transitions'].append({ "event": "failed", "next": None })
                
            if 'from' not in state.get('properties', {}):
                state['properties']['from'] = "{{flow.channel.address}}"

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Archivo sanitizado: {os.path.basename(filepath)}")

archivos = glob.glob("flow*.json")

if not archivos:
    print("⚠️ ALERTA: No se encontraron archivos JSON en esta carpeta.")
else:
    print("Iniciando sanitización de flujos...\n")
    for archivo in archivos:
        fix_flow(archivo)
    print("\n🚀 ¡Todos los flujos están listos para Twilio!")