# Integração Emops

eContador (Alterdata Pack) → CSV → ifPonto/stou (`https://stou.ifractal.com.br/emops/rest/`).

Empresas: **9 Emops**, **10 Efire**, **11 Econtrol**.  
Departamentos ignorados: **940 MAPA AP**, **973 MAPA RORAIMA**.

## Local

```bash
cp .config.exemplo .config   # preencher credenciais
python -m venv .venv
# Windows: .\.venv\Scripts\Activate.ps1
# Linux:   source .venv/bin/activate
pip install -r requirements.txt

python funcionarios.py csv
python funcionarios.py enviar
# ou fluxo completo:
python main.py
```

O `.config` **não** vai para o Git.

## Servidor

Caminho: `/home/gogotech/integracao/emops`  
Repositório: https://github.com/AndrewsGama-Dev/emops.git  

Passo a passo: **[DEPLOY_SERVIDOR.md](DEPLOY_SERVIDOR.md)**
