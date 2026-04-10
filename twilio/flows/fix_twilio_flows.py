import json
import os
import tkinter as tk
from tkinter import filedialog

def fix_flow(filepath):
    try:
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
        
        print(f"✅ Reparado y listo para Twilio: {os.path.basename(filepath)}")
    except Exception as e:
        print(f"❌ Error con {os.path.basename(filepath)}: {str(e)}")

# Crear una ventana invisible
root = tk.Tk()
root.withdraw()
# Poner la ventana por encima de todo
root.attributes('-topmost', True)

print("Abriendo ventana para seleccionar archivos...")

# Abrir el selector de archivos (puedes seleccionar los 5 al tiempo)
archivos = filedialog.askopenfilenames(
    title="Selecciona tus 5 archivos JSON de Twilio",
    filetypes=[("Archivos JSON", "*.json")]
)

if not archivos:
    print("No seleccionaste ningún archivo. Cancelando.")
else:
    print(f"\nProcesando {len(archivos)} archivos seleccionados...\n")
    for archivo in archivos:
        fix_flow(archivo)
    print("\n🚀 ¡TODO LISTO! Ya puedes importarlos en Twilio Studio.")