param([int]$Port=8899)
$ErrorActionPreference='Stop'
$ragRoot=Join-Path (Split-Path $PSScriptRoot -Parent) 'local_rag'
Set-Location -LiteralPath $ragRoot
$env:LOCAL_RAG_MYSQL_DATABASE='local_rag_agent_eval'
$env:LOCAL_RAG_MILVUS_COLLECTION='local_rag_eval_experiences'
$env:LOCAL_RAG_PDF_COLLECTION='local_rag_eval_documents'
$env:LOCAL_RAG_DATA_DIR=Join-Path $ragRoot 'data/agent_eval'
& 'E:/Python3127/python.exe' -m uvicorn rag.research_app:app --host 127.0.0.1 --port $Port
