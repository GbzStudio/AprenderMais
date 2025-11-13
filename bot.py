# bot.py
# Exemplo seguro: consome tarefas do Realtime Database e processa
# Requisitos: pip install firebase-admin requests

import os, json, time
import firebase_admin
from firebase_admin import credentials, db
import requests

# Carrega credencial da service account a partir da variável de ambiente (JSON)
sa_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
if not sa_json:
    raise SystemExit("ERRO: defina a variável FIREBASE_SERVICE_ACCOUNT_JSON com o JSON do service account (no GitHub secret)")

sa = json.loads(sa_json)
cred = credentials.Certificate(sa)
# inicializa app (evita múltiplas inicializações)
try:
    firebase_admin.get_app()
except ValueError:
    firebase_admin.initialize_app(cred, {
        'databaseURL': sa.get('databaseURL') or "https://fir-auth-3521c-default-rtdb.firebaseio.com"
    })

REF = db.reference('adminTasks')

def process_task(key, task):
    """
    task = { 'title':..., 'type': ..., 'payload': {...}, 'status': 'queued' }
    Tipos suportados (exemplo seguro):
      - http_request: faz um request HTTP para uma URL fornecida no payload (GET/POST)
      - generate_file: gera um arquivo txt com conteúdo do payload e salva em /botOutputs (DB)
    Não execute ações perigosas sem validação.
    """
    print(f"Processando {key}: {task.get('title')}")
    REF.child(key).update({'status': 'processing', 'startedAt': int(time.time()*1000)})
    ttype = task.get('type')
    payload = task.get('payload') or {}
    result = {'ok': False, 'info': None}

    try:
        if ttype == 'http_request':
            url = payload.get('url')
            method = (payload.get('method') or 'GET').upper()
            if not url:
                raise ValueError("payload.url obrigatório para http_request")
            # segurança: permita apenas http(s) e evite local addresses
            if not (url.startswith('http://') or url.startswith('https://')):
                raise ValueError("URL inválida")
            # simples timeout
            r = requests.request(method, url, timeout=15, params=payload.get('params'), json=payload.get('json'))
            result['ok'] = True
            result['info'] = {'status_code': r.status_code, 'text_snippet': r.text[:800]}
        elif ttype == 'generate_file':
            content = payload.get('content', '')
            filename = payload.get('filename', f"output_{int(time.time())}.txt")
            # salva no DB em /botOutputs (pode ser lido por front-end)
            out_ref = db.reference('botOutputs').push()
            out_ref.set({
                'filename': filename,
                'content': content,
                'createdAt': int(time.time()*1000)
            })
            result['ok'] = True
            result['info'] = {'savedRef': out_ref.key}
        else:
            result['ok'] = False
            result['info'] = f"Tipo não suportado: {ttype}"
    except Exception as e:
        result['ok'] = False
        result['info'] = str(e)

    # grava resultado no nó da tarefa
    REF.child(key).update({
        'status': 'done' if result['ok'] else 'failed',
        'result': result,
        'finishedAt': int(time.time()*1000)
    })
    print("Resultado:", result)

def poll_and_process():
    print("Worker iniciado — checando fila...")
    while True:
        try:
            snap = REF.order_by_child('status').equal_to('queued').limit_to_first(5).get()
            if not snap:
                print("Sem tarefas na fila — sleeping 10s")
                time.sleep(10)
                continue
            for key, task in snap.items():
                process_task(key, task)
            # pequena pausa entre batches
            time.sleep(1)
        except Exception as e:
            print("Erro no loop:", e)
            time.sleep(8)

if __name__ == '__main__':
    poll_and_process()
