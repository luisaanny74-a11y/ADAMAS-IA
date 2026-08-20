import os
import json
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import bcrypt
import ollama
import docx
from pypdf import PdfReader

app = Flask(__name__)
CORS(app)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///adamas.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'adamas-dev-key-mude-em-producao')

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login_page'

UPLOAD_FOLDER = 'temp_files'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# ══════════════════════════════════════════════════════════
# MODELOS DO BANCO
# ══════════════════════════════════════════════════════════

class Usuario(UserMixin, db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    nome       = db.Column(db.String(100), nullable=False)
    email      = db.Column(db.String(200), unique=True, nullable=False)
    senha_hash = db.Column(db.String(200), nullable=False)
    criado_em  = db.Column(db.DateTime, default=datetime.utcnow)

    def set_senha(self, senha):
        self.senha_hash = bcrypt.hashpw(
            senha.encode('utf-8'), bcrypt.gensalt()
        ).decode('utf-8')

    def check_senha(self, senha):
        return bcrypt.checkpw(
            senha.encode('utf-8'),
            self.senha_hash.encode('utf-8')
        )

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Usuario, int(user_id))

class Documento(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    nome      = db.Column(db.String(500), unique=True, nullable=False)
    conteudo  = db.Column(db.Text, nullable=False)
    modo      = db.Column(db.String(20), default='consulta')
    mensagens = db.relationship('Mensagem', backref='documento',
                                cascade='all, delete-orphan', lazy=True)
    sessoes   = db.relationship('SessaoSabatina', backref='documento',
                                cascade='all, delete-orphan', lazy=True)

class Mensagem(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    role          = db.Column(db.String(20), nullable=False)
    content       = db.Column(db.Text, nullable=False)
    pergunta_pura = db.Column(db.Text, nullable=True)
    documento_id  = db.Column(db.Integer, db.ForeignKey('documento.id'), nullable=False)

class SessaoSabatina(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    documento_id = db.Column(db.Integer, db.ForeignKey('documento.id'), nullable=False)
    data         = db.Column(db.DateTime, default=datetime.utcnow)
    total        = db.Column(db.Integer, default=0)
    correto      = db.Column(db.Integer, default=0)
    parcial      = db.Column(db.Integer, default=0)
    incorreto    = db.Column(db.Integer, default=0)
    percentual   = db.Column(db.Float, default=0.0)
    avaliacao    = db.Column(db.String(100), default='')
    detalhes     = db.Column(db.Text, default='[]')

with app.app_context():
    db.create_all()

# ══════════════════════════════════════════════════════════
# ESTADO EM MEMÓRIA
# ══════════════════════════════════════════════════════════

placar_por_documento = {}
contexto_atual       = ""
documento_atual_nome = ""

MODEL = 'mistral'

# ══════════════════════════════════════════════════════════
# GATILHOS
# ══════════════════════════════════════════════════════════

GATILHOS_SABATINA = [
    'sabatina', 'sabatinar', 'me teste', 'me testa', 'quero ser testado',
    'quero ser avaliado', 'faz uma prova', 'fazer prova', 'modo sabatina',
    'iniciar sabatina', 'comecar sabatina', 'quero prova', 'me avalie',
    'teste meu conhecimento', 'avalie meu conhecimento'
]

GATILHOS_FIM_SABATINA = [
    'fim', 'pare', 'chega', 'encerrar', 'encerra', 'parar', 'stop',
    'fechar', 'fechar sabatina', 'encerrar sabatina', 'parar sabatina',
    'sair da sabatina', 'sair do modo', 'voltar ao normal',
    'chega de sabatina', 'fim da sabatina', 'finalizar sabatina',
    'terminar sabatina', 'terminar', 'acabar', 'acabar sabatina',
    'quero sair', 'sair', 'cancelar', 'cancelar sabatina',
    'encerrar modo', 'fechar modo', 'parar modo'
]

SAUDACOES = [
    'olá', 'ola', 'oi', 'hey', 'hello', 'bom dia', 'boa tarde', 'boa noite',
    'e aí', 'e ai', 'tudo bem', 'tudo bom', 'salve', 'opa'
]

# ══════════════════════════════════════════════════════════
# HELPERS DO BANCO
# ══════════════════════════════════════════════════════════

def get_doc(nome):
    return Documento.query.filter_by(nome=nome).first()

def historico_para_lista(doc):
    return [
        {"role": m.role, "content": m.content, "pergunta_pura": m.pergunta_pura}
        for m in doc.mensagens
    ]

def salvar_mensagem(doc, role, content, pergunta_pura=None):
    m = Mensagem(role=role, content=content,
                 pergunta_pura=pergunta_pura, documento_id=doc.id)
    db.session.add(m)

def limpar_mensagens(doc):
    Mensagem.query.filter_by(documento_id=doc.id).delete()

# ══════════════════════════════════════════════════════════
# DETECÇÃO DE MODO
# ══════════════════════════════════════════════════════════

def detectar_modo(msg, modo_atual):
    msg_lower = msg.lower().strip()
    palavras  = msg_lower.split()

    if modo_atual == 'sabatina':
        if len(palavras) <= 5:
            for g in GATILHOS_FIM_SABATINA:
                if msg_lower == g or msg_lower.startswith(g + ' ') or msg_lower.endswith(' ' + g):
                    return 'consulta'
    else:
        for g in GATILHOS_FIM_SABATINA:
            if g in msg_lower:
                return 'consulta'

    for g in GATILHOS_SABATINA:
        if g in msg_lower:
            return 'sabatina'

    return modo_atual

def eh_saudacao(msg):
    msg_lower = msg.lower().strip()
    for s in SAUDACOES:
        if msg_lower.startswith(s) and len(msg_lower.split()) <= 6:
            return True
    return False

def resposta_saudacao():
    return (
        "Olá! ADAMAS a seu dispor!\n"
        "Envie sua dúvida ou peça uma explicação sobre o conteúdo do arquivo.\n"
        "Digite 'sabatina' quando quiser ser testado."
    )

# ══════════════════════════════════════════════════════════
# CLASSIFICADOR ISOLADO
# ══════════════════════════════════════════════════════════

def classificar_resposta(pergunta, resposta_usuario, contexto):
    resp_lower = resposta_usuario.lower().strip()
    perg_lower = pergunta.lower().strip()

    RESPOSTAS_INVALIDAS = [
        'não sei', 'nao sei', 'sei não', 'sei nao', 'n sei',
        'não tenho ideia', 'nao tenho ideia', 'sem ideia',
        'nenhuma ideia', 'ideia nenhuma', 'não lembro', 'nao lembro',
        'não lembro não', 'esqueci', 'não faço ideia', 'nao faco ideia',
        'não sei não', 'sei lá', 'sei la', 'talvez', 'acho que não',
        'não me lembro', 'não recordo', 'zero ideia', 'sem noção',
        'não tenho certeza', 'nao tenho certeza', 'não tenho conhecimento'
    ]
    for invalida in RESPOSTAS_INVALIDAS:
        if resp_lower == invalida or resp_lower.startswith(invalida + ' ') or resp_lower.startswith(invalida + ','):
            return 'INCORRETO'

    STOPWORDS = {'o', 'a', 'os', 'as', 'um', 'uma', 'de', 'do', 'da', 'dos', 'das',
                 'em', 'no', 'na', 'nos', 'nas', 'por', 'para', 'com', 'que', 'qual',
                 'quais', 'e', 'ou', 'se', 'ao', 'como', 'quando', 'onde',
                 'entre', 'sobre', 'sua', 'seu', 'ser', 'esta', 'sao', 'foi',
                 'tem', 'ter', 'diagrama', 'significado'}

    TERMOS_FORA_ESCOPO = [
        'banco de dados', 'database', 'mysql', 'postgresql', 'mongodb',
        'javascript', 'python', 'java', 'flutter', 'dart', 'react',
        'dba', 'sgbd', 'crud', 'select', 'insert', 'delete', 'update',
        'html', 'css', 'php', 'ruby', 'golang', 'kotlin', 'swift'
    ]

    palavras_perg = set(perg_lower.split()) - STOPWORDS
    palavras_resp = set(resp_lower.split()) - STOPWORDS
    resp_tem_termo_fora   = any(t in resp_lower for t in TERMOS_FORA_ESCOPO)
    resp_tem_palavra_perg = bool(palavras_perg & palavras_resp)

    if len(palavras_resp) <= 3 and not resp_tem_palavra_perg:
        if resp_tem_termo_fora and not resp_tem_palavra_perg:
            return 'INCORRETO'

    msgs = [
        {
            "role": "system",
            "content": (
                "Você é um avaliador técnico rigoroso. "
                "Avalie APENAS se a resposta do usuário está correta com base no conteúdo.\n\n"
                f"CONTEÚDO:\n'''{contexto[:8000]}'''\n\n"
                "CLASSIFICAÇÕES:\n"
                "- CORRETO: tecnicamente precisa e completa.\n"
                "- PARCIALMENTE CORRETO: tem acerto mas incompleta ou imprecisa.\n"
                "- INCORRETO: errada, vaga, sem sentido técnico ou chute.\n\n"
                "Respostas vagas ou sem conhecimento = INCORRETO.\n"
                "Responda SOMENTE com uma dessas palavras:\n"
                "CORRETO\nPARCIALMENTE CORRETO\nINCORRETO"
            )
        },
        {"role": "user", "content": f"Pergunta: {pergunta}\nResposta do usuário: {resposta_usuario}"}
    ]
    try:
        result = ollama.chat(model=MODEL, messages=msgs)
        c = result['message']['content'].strip().upper()
        if 'PARCIALMENTE' in c: return 'PARCIALMENTE CORRETO'
        elif 'INCORRETO'  in c: return 'INCORRETO'
        elif 'CORRETO'    in c: return 'CORRETO'
        return 'INCORRETO'
    except:
        return 'INCORRETO'

# ══════════════════════════════════════════════════════════
# EXPLICAÇÃO
# ══════════════════════════════════════════════════════════

def gerar_explicacao(pergunta, resposta_usuario, classificacao, contexto):
    instrucoes = {
        'CORRETO': (
            "A resposta está CORRETA. Escreva UMA frase curta confirmando o acerto. "
            "Fale APENAS sobre o que foi perguntado. NÃO antecipe o próximo assunto."
        ),
        'PARCIALMENTE CORRETO': (
            "A resposta está PARCIALMENTE CORRETA. Em no máximo 3 frases: "
            "diga o que está certo, corrija o que está errado. "
            "Use SOMENTE informações do conteúdo de referência."
        ),
        'INCORRETO': (
            "A resposta está INCORRETA. Em no máximo 3 frases: "
            "diga por que está errada e qual é a correta. "
            "Use SOMENTE informações do conteúdo de referência. "
            "NÃO invente detalhes que não estejam no texto."
        )
    }
    msgs = [
        {
            "role": "system",
            "content": (
                f"CONTEÚDO DE REFERÊNCIA:\n'''{contexto[:8000]}'''\n\n"
                f"INSTRUÇÃO: {instrucoes[classificacao]}\n\n"
                "PROIBIÇÕES:\n"
                "- Responda SEMPRE em português brasileiro.\n"
                "- NÃO faça perguntas.\n"
                "- NÃO use [CORRETO] ou similares.\n"
                "- NÃO elogie excessivamente."
            )
        },
        {"role": "user", "content": f"Pergunta: {pergunta}\nResposta: {resposta_usuario}"}
    ]
    try:
        result = ollama.chat(model=MODEL, messages=msgs)
        return result['message']['content'].strip()
    except:
        return "Não foi possível gerar a explicação."

# ══════════════════════════════════════════════════════════
# PRÓXIMA PERGUNTA
# ══════════════════════════════════════════════════════════

def gerar_proxima_pergunta(historico, contexto):
    perguntas_feitas = []
    for m in historico:
        if m["role"] == "assistant":
            pura = m.get("pergunta_pura") or ""
            if pura:
                perguntas_feitas.append(pura[:200])
            else:
                linhas = m["content"].strip().split("\n")
                ultima = linhas[-1].strip() if linhas else ""
                if ultima.endswith("?"):
                    perguntas_feitas.append(ultima[:200])

    perguntas_str = "\n".join(f"- {p}" for p in perguntas_feitas) if perguntas_feitas else "Nenhuma ainda."

    msgs = [
        {
            "role": "system",
            "content": (
                f"CONTEÚDO DE REFERÊNCIA:\n'''{contexto[:8000]}'''\n\n"
                f"PERGUNTAS JÁ FEITAS (não repita):\n{perguntas_str}\n\n"
                "INSTRUÇÃO:\n"
                "- Use SEMPRE o português brasileiro.\n"
                "- Faça UMA pergunta técnica sobre UM único conceito.\n"
                "- Máximo 20 palavras. Termine com '?'.\n"
                "- NÃO use 'e' para unir dois conceitos.\n"
                "- Responda APENAS com a pergunta."
            )
        },
        {"role": "user", "content": "Faça a próxima pergunta."}
    ]
    try:
        result = ollama.chat(model=MODEL, messages=msgs)
        pergunta = result['message']['content'].strip()
        for prefix in ['1.', '2.', '3.', 'Pergunta:', 'P:']:
            if pergunta.startswith(prefix):
                pergunta = pergunta[len(prefix):].strip()
        if not pergunta.endswith('?'):
            pergunta += '?'
        return pergunta
    except:
        return "Qual outro conceito importante você aprendeu neste conteúdo?"

# ══════════════════════════════════════════════════════════
# MONTAGEM DA RESPOSTA
# ══════════════════════════════════════════════════════════

def montar_resposta_sabatina(pergunta, resposta_usuario, classificacao,
                              historico, contexto, doc_nome, prox_pergunta_ref=None):
    prefixos = {
        'CORRETO':              '[CORRETO]',
        'PARCIALMENTE CORRETO': '[PARCIALMENTE CORRETO]',
        'INCORRETO':            '[INCORRETO]'
    }

    if doc_nome not in placar_por_documento:
        placar_por_documento[doc_nome] = {
            'correto': 0, 'parcial': 0, 'incorreto': 0, 'detalhes': []
        }

    placar = placar_por_documento[doc_nome]
    if classificacao == 'CORRETO':         placar['correto']  += 1
    elif classificacao == 'PARCIALMENTE CORRETO': placar['parcial']  += 1
    else:                                  placar['incorreto'] += 1

    placar['detalhes'].append({
        'pergunta':      pergunta[:200],
        'resposta':      resposta_usuario[:200],
        'classificacao': classificacao
    })

    explicacao    = gerar_explicacao(pergunta, resposta_usuario, classificacao, contexto)
    prox_pergunta = gerar_proxima_pergunta(historico, contexto)

    if prox_pergunta_ref is not None:
        prox_pergunta_ref[0] = prox_pergunta

    return f"{prefixos[classificacao]} — {explicacao}\n\n{prox_pergunta}"

# ══════════════════════════════════════════════════════════
# RESUMO FINAL
# ══════════════════════════════════════════════════════════

def gerar_resumo_final(doc_nome, doc_obj):
    if doc_nome not in placar_por_documento:
        return "Sabatina encerrada. Nenhuma pergunta foi respondida."

    placar = placar_por_documento[doc_nome]
    total  = placar['correto'] + placar['parcial'] + placar['incorreto']

    if total == 0:
        return "Sabatina encerrada. Nenhuma pergunta foi respondida."

    pct = round((placar['correto'] / total) * 100)
    if pct >= 80:   avaliacao = "Desempenho sólido. Domínio adequado do conteúdo."
    elif pct >= 50: avaliacao = "Desempenho parcial. Revise os pontos incorretos antes da prova."
    else:           avaliacao = "Desempenho insuficiente. Recomenda-se rever o material completo."

    sessao = SessaoSabatina(
        documento_id=doc_obj.id, total=total,
        correto=placar['correto'], parcial=placar['parcial'],
        incorreto=placar['incorreto'], percentual=pct,
        avaliacao=avaliacao,
        detalhes=json.dumps(placar['detalhes'], ensure_ascii=False)
    )
    db.session.add(sessao)

    linhas = ["◈ RESUMO DA SABATINA\n"]
    linhas.append(f"Total de perguntas: {total}")
    linhas.append(f"✓ Corretas:              {placar['correto']}")
    linhas.append(f"~ Parcialmente corretas: {placar['parcial']}")
    linhas.append(f"✗ Incorretas:            {placar['incorreto']}\n")

    if placar['detalhes']:
        linhas.append("Detalhes:")
        for i, d in enumerate(placar['detalhes'], 1):
            s = '✓' if d['classificacao'] == 'CORRETO' else ('~' if d['classificacao'] == 'PARCIALMENTE CORRETO' else '✗')
            linhas.append(f"{i}. [{s}] {d['pergunta']}")
            linhas.append(f"    Resposta: {d['resposta']}")
            linhas.append(f"    Resultado: {d['classificacao']}\n")

    linhas.append(f"Avaliação: {avaliacao}")
    linhas.append("\nModo consulta reativado.")

    placar_por_documento[doc_nome] = {'correto': 0, 'parcial': 0, 'incorreto': 0, 'detalhes': []}
    return "\n".join(linhas)

# ══════════════════════════════════════════════════════════
# PROMPTS
# ══════════════════════════════════════════════════════════

def prompt_consulta(contexto):
    return (
        "Você é o ADAMAS, um assistente técnico de estudos objetivo e preciso.\n\n"
        "CONTEÚDO DE REFERÊNCIA:\n"
        f"'''{contexto[:8000]}'''\n\n"
        "INSTRUÇÕES:\n"
        "- Responda SEMPRE em português brasileiro.\n"
        "- Responda APENAS o que o usuário perguntou. Nada mais.\n"
        "- Se o usuário fizer uma saudação, responda brevemente e pergunte em que pode ajudar.\n"
        "- NUNCA apresente ou resuma o conteúdo espontaneamente.\n"
        "- Seja direto, técnico e claro. Não invente informações.\n"
        "- Ao final, informe que o usuário pode digitar 'sabatina' para ser testado."
    )

def prompt_inicio_sabatina(contexto):
    return (
        "Você é o ADAMAS, um examinador técnico rigoroso.\n\n"
        f"CONTEÚDO DE REFERÊNCIA:\n'''{contexto[:8000]}'''\n\n"
        "INSTRUÇÃO: Faça a primeira pergunta técnica sobre o conteúdo.\n"
        "REGRAS:\n"
        "- Use SEMPRE o português brasileiro.\n"
        "- UMA pergunta sobre UM único conceito. Máximo 20 palavras.\n"
        "- Sem introduções. Apenas a pergunta, terminando com '?'."
    )

# ══════════════════════════════════════════════════════════
# EXTRAÇÃO DE TEXTO
# ══════════════════════════════════════════════════════════

def extrair_texto(caminho):
    ext = caminho.split('.')[-1].lower()
    try:
        if ext == 'docx':
            doc = docx.Document(caminho)
            return "\n".join([p.text for p in doc.paragraphs])
        elif ext == 'pdf':
            reader = PdfReader(caminho)
            return "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
        elif ext in ['txt', 'py', 'sql', 'html', 'css', 'js']:
            with open(caminho, 'r', encoding='utf-8') as f:
                return f.read()
        return ""
    except Exception as e:
        print(f"Erro na extração: {e}")
        return ""

# ══════════════════════════════════════════════════════════
# AUTENTICAÇÃO
# ══════════════════════════════════════════════════════════

@app.route('/login', methods=['GET'])
def login_page():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login_post():
    data  = request.json
    email = data.get('email', '').strip().lower()
    senha = data.get('senha', '')
    if not email or not senha:
        return jsonify({"ok": False, "erro": "Preencha e-mail e senha."}), 400
    usuario = Usuario.query.filter_by(email=email).first()
    if not usuario or not usuario.check_senha(senha):
        return jsonify({"ok": False, "erro": "E-mail ou senha incorretos."}), 401
    login_user(usuario, remember=True)
    return jsonify({"ok": True, "nome": usuario.nome})

@app.route('/cadastro', methods=['POST'])
def cadastro_post():
    data  = request.json
    nome  = data.get('nome', '').strip()
    email = data.get('email', '').strip().lower()
    senha = data.get('senha', '')
    if not nome or not email or not senha:
        return jsonify({"ok": False, "erro": "Preencha todos os campos."}), 400
    if len(senha) < 6:
        return jsonify({"ok": False, "erro": "A senha deve ter pelo menos 6 caracteres."}), 400
    if Usuario.query.filter_by(email=email).first():
        return jsonify({"ok": False, "erro": "Este e-mail ja esta cadastrado."}), 409
    usuario = Usuario(nome=nome, email=email)
    usuario.set_senha(senha)
    db.session.add(usuario)
    db.session.commit()
    login_user(usuario, remember=True)
    return jsonify({"ok": True, "nome": nome})

@app.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return jsonify({"ok": True})

@app.route('/me', methods=['GET'])
@login_required
def me():
    return jsonify({"nome": current_user.nome, "email": current_user.email})

# ══════════════════════════════════════════════════════════
# ROTAS PRINCIPAIS
# ══════════════════════════════════════════════════════════

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/reset', methods=['POST'])
@login_required
def reset():
    global contexto_atual, documento_atual_nome
    with app.app_context():
        doc = get_doc(documento_atual_nome)
        if doc:
            limpar_mensagens(doc)
            doc.modo = 'consulta'
            db.session.commit()
    placar_por_documento[documento_atual_nome] = {
        'correto': 0, 'parcial': 0, 'incorreto': 0, 'detalhes': []
    }
    contexto_atual = ""
    return jsonify({"message": "Protocolo de purga concluído."})

@app.route('/clear-context', methods=['POST'])
@login_required
def clear_context():
    global contexto_atual, documento_atual_nome
    with app.app_context():
        doc = get_doc(documento_atual_nome)
        if doc:
            limpar_mensagens(doc)
            doc.modo = 'consulta'
            db.session.commit()
    contexto_atual = ""
    return jsonify({"message": "Fragmento desconectado."})

@app.route('/upload', methods=['POST'])
@login_required
def upload():
    global contexto_atual, documento_atual_nome
    if 'file' not in request.files:
        return jsonify({"error": "Nenhum arquivo"}), 400

    file     = request.files['file']
    filepath = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(filepath)
    texto = extrair_texto(filepath)

    if texto:
        contexto_atual       = texto
        documento_atual_nome = file.filename

        with app.app_context():
            doc = get_doc(file.filename)
            if not doc:
                doc = Documento(nome=file.filename, conteudo=texto, modo='consulta')
                db.session.add(doc)
                db.session.commit()
                chat_history = []
            else:
                doc.conteudo = texto
                doc.modo     = 'consulta'
                db.session.commit()
                chat_history = [
                    {"role": m.role, "content": m.content}
                    for m in doc.mensagens
                    if m.role in ('user', 'assistant')
                ]

        os.remove(filepath)
        return jsonify({
            "text":              "Documento indexado!",
            "filename":          file.filename,
            "extracted_content": texto,
            "chat_history":      chat_history
        })
    else:
        if os.path.exists(filepath):
            os.remove(filepath)
        return jsonify({"error": "Erro ao ler arquivo."}), 400

@app.route('/switch-context', methods=['POST'])
@login_required
def switch_context():
    global contexto_atual, documento_atual_nome
    data     = request.json
    content  = data.get("content", "").strip()
    filename = data.get("filename", "").strip()
    if not content:
        return jsonify({"ok": False, "error": "Conteúdo vazio."}), 400

    contexto_atual       = content
    documento_atual_nome = filename

    with app.app_context():
        doc = get_doc(filename)
        if not doc:
            doc = Documento(nome=filename, conteudo=content, modo='consulta')
            db.session.add(doc)
            db.session.commit()
            chat_history = []
        else:
            doc.conteudo = content
            doc.modo     = 'consulta'
            db.session.commit()
            chat_history = [
                {"role": m.role, "content": m.content}
                for m in doc.mensagens
                if m.role in ('user', 'assistant')
            ]

    return jsonify({"ok": True, "chat_history": chat_history, "modo": "consulta"})

@app.route('/delete-doc', methods=['POST'])
@login_required
def delete_doc():
    global contexto_atual, documento_atual_nome
    data     = request.json
    filename = data.get("filename", "").strip()
    if not filename:
        return jsonify({"ok": False, "error": "Nome inválido."}), 400

    with app.app_context():
        doc = get_doc(filename)
        if doc:
            db.session.delete(doc)
            db.session.commit()

    if documento_atual_nome == filename:
        contexto_atual       = ""
        documento_atual_nome = ""
        placar_por_documento.pop(filename, None)

    return jsonify({"ok": True})

@app.route('/dashboard', methods=['GET'])
@login_required
def dashboard():
    with app.app_context():
        documentos = Documento.query.all()
        resultado  = []
        for doc in documentos:
            sessoes = (SessaoSabatina.query
                       .filter_by(documento_id=doc.id)
                       .order_by(SessaoSabatina.data.asc())
                       .all())
            if not sessoes:
                continue
            sessoes_data = []
            for s in sessoes:
                try:    detalhes = json.loads(s.detalhes) if s.detalhes else []
                except: detalhes = []
                sessoes_data.append({
                    "id": s.id, "data": s.data.strftime('%d/%m/%Y %H:%M'),
                    "total": s.total, "correto": s.correto,
                    "parcial": s.parcial, "incorreto": s.incorreto,
                    "percentual": s.percentual, "avaliacao": s.avaliacao,
                    "detalhes": detalhes
                })
            resultado.append({"documento": doc.nome, "sessoes": sessoes_data})
    return jsonify({"ok": True, "dados": resultado})

@app.route('/get-chat-history', methods=['POST'])
@login_required
def get_chat_history():
    data     = request.json
    filename = data.get("filename", "")
    if not filename:
        return jsonify({"ok": False, "history": []})
    with app.app_context():
        doc = get_doc(filename)
        if not doc:
            return jsonify({"ok": True, "history": []})
        history = [
            {"role": m.role, "content": m.content}
            for m in doc.mensagens if m.role in ('user', 'assistant')
        ]
    return jsonify({"ok": True, "history": history})

@app.route('/chat', methods=['POST'])
@login_required
def chat():
    global contexto_atual, documento_atual_nome
    data = request.json
    msg  = data.get("message", "")

    if not contexto_atual:
        return jsonify({"reply": "Aguardando sincronização de fragmento técnico (PDF/DOCX)."})

    with app.app_context():
        doc = get_doc(documento_atual_nome)
        if not doc:
            return jsonify({"reply": "Documento não encontrado no banco."})

        modo_anterior = doc.modo
        novo_modo     = detectar_modo(msg, modo_anterior)
        doc.modo      = novo_modo
        historico     = historico_para_lista(doc)
        reply         = ""

        if novo_modo == 'sabatina' and modo_anterior != 'sabatina':
            limpar_mensagens(doc)
            historico = []
            placar_por_documento[documento_atual_nome] = {
                'correto': 0, 'parcial': 0, 'incorreto': 0, 'detalhes': []
            }
            msgs_ollama = [
                {"role": "system", "content": prompt_inicio_sabatina(contexto_atual)},
                {"role": "user",   "content": "Inicie a sabatina."}
            ]
            try:
                result = ollama.chat(model=MODEL, messages=msgs_ollama)
                reply  = result['message']['content'].strip()
                if not reply.endswith('?'):
                    reply += '?'
                salvar_mensagem(doc, 'assistant', reply, pergunta_pura=reply)
            except:
                reply = "Erro ao iniciar sabatina."

        elif novo_modo == 'consulta' and modo_anterior == 'sabatina':
            reply = gerar_resumo_final(documento_atual_nome, doc)
            limpar_mensagens(doc)
            salvar_mensagem(doc, 'assistant', reply)

        elif novo_modo == 'sabatina':
            ultima_msg = (Mensagem.query
                          .filter_by(documento_id=doc.id, role='assistant')
                          .order_by(Mensagem.id.desc()).first())
            ultima_pergunta = ""
            if ultima_msg:
                ultima_pergunta = ultima_msg.pergunta_pura or ultima_msg.content

            classificacao = classificar_resposta(ultima_pergunta, msg, contexto_atual)
            salvar_mensagem(doc, 'user', msg)
            historico = historico_para_lista(doc)

            prox_ref = [None]
            reply = montar_resposta_sabatina(
                ultima_pergunta, msg, classificacao,
                historico, contexto_atual, documento_atual_nome, prox_ref
            )
            salvar_mensagem(doc, 'assistant', reply, pergunta_pura=prox_ref[0])

        else:
            if eh_saudacao(msg):
                reply = resposta_saudacao()
                salvar_mensagem(doc, 'user', msg)
                salvar_mensagem(doc, 'assistant', reply)
            else:
                msgs_ollama = [{"role": "system", "content": prompt_consulta(contexto_atual)}]
                for m in historico:
                    if m["role"] in ('user', 'assistant'):
                        msgs_ollama.append({"role": m["role"], "content": m["content"]})
                msgs_ollama.append({"role": "user", "content": msg})
                try:
                    result = ollama.chat(model=MODEL, messages=msgs_ollama)
                    reply  = result['message']['content']
                except:
                    reply = "Erro no núcleo ADAMAS."
                salvar_mensagem(doc, 'user', msg)
                salvar_mensagem(doc, 'assistant', reply)

        db.session.commit()

    placar_atual = None
    if novo_modo == 'sabatina' and documento_atual_nome in placar_por_documento:
        pl = placar_por_documento[documento_atual_nome]
        placar_atual = {
            "correto":   pl["correto"],
            "parcial":   pl["parcial"],
            "incorreto": pl["incorreto"],
            "total":     pl["correto"] + pl["parcial"] + pl["incorreto"]
        }

    return jsonify({"reply": reply, "modo": novo_modo, "placar": placar_atual})

if __name__ == '__main__':
    app.run(debug=True, port=5000, threaded=True)