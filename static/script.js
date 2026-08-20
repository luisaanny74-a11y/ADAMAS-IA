let scene, camera, renderer, ruby, currentFileContent = "";
let isThinking = false;

let sessionLog     = [];
let currentDocName = "";

let thinkingEl = null;

function init() {
    const container = document.getElementById('canvas-container');
    const width  = container.clientWidth;
    const height = container.clientHeight;

    scene  = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(75, width / height, 0.1, 1000);

    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(width, height);
    container.appendChild(renderer.domElement);

    const geometry = new THREE.OctahedronGeometry(2, 0);
    const material = new THREE.MeshPhongMaterial({
        color: 0x800000, emissive: 0xff0000,
        emissiveIntensity: 0.2, flatShading: true, shininess: 120
    });
    ruby = new THREE.Mesh(geometry, material);
    scene.add(ruby);

    const pl1 = new THREE.PointLight(0xff2200, 2, 100);
    pl1.position.set(5, 5, 5);
    scene.add(pl1);

    const pl2 = new THREE.PointLight(0x880000, 1, 100);
    pl2.position.set(-5, -3, -5);
    scene.add(pl2);

    scene.add(new THREE.AmbientLight(0x220000));
    camera.position.z = 6;
    animate();
}

function animate() {
    requestAnimationFrame(animate);
    const speed     = isThinking ? 0.05  : 0.005;
    const intensity = isThinking ? 1.2   : 0.2;
    ruby.rotation.y += speed;
    ruby.rotation.x += speed * 0.4;
    ruby.material.emissiveIntensity = THREE.MathUtils.lerp(
        ruby.material.emissiveIntensity, intensity, 0.05
    );
    renderer.render(scene, camera);
}

function onWindowResize() {
    const sidebar      = document.getElementById('sidebar');
    const sidebarWidth = sidebar.classList.contains('collapsed') ? 56 : 240;
    camera.aspect = (window.innerWidth - sidebarWidth) / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth - sidebarWidth, window.innerHeight);
}

function getHistorico() {
    try { return JSON.parse(localStorage.getItem('adamas_docs') || "[]"); }
    catch { return []; }
}

function saveDocToHistorico(name, content) {
    let docs = getHistorico().filter(d => d.name !== name);
    try {
        localStorage.setItem('adamas_docs',
            JSON.stringify([{ name, content }, ...docs].slice(0, 10)));
    } catch (e) { console.warn("Storage cheio:", e); }
}

function removeDocDoHistorico(name) {
    let docs = getHistorico().filter(d => d.name !== name);
    localStorage.setItem('adamas_docs', JSON.stringify(docs));
}

function carregarHistorico() {
    const lista = document.getElementById('history-list');
    const docs  = getHistorico();
    lista.innerHTML = "";

    docs.forEach(doc => {
        const div = document.createElement('div');
        div.className = 'history-item';
        div.title     = doc.name;

        const gemSpan  = document.createElement('span');
        gemSpan.style.cssText = 'color:#ff3333;font-size:0.7rem;flex-shrink:0;';
        gemSpan.textContent   = '◈';

        const nameSpan = document.createElement('span');
        nameSpan.className   = 'history-item-name';
        nameSpan.textContent = doc.name;

        const delBtn = document.createElement('button');
        delBtn.className   = 'history-delete-btn';
        delBtn.title       = 'Remover documento';
        delBtn.textContent = '✕';
        delBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            deletarDocumento(doc.name);
        });

        div.appendChild(gemSpan);
        div.appendChild(nameSpan);
        div.appendChild(delBtn);
        div.addEventListener('click', () => trocarDocumento(doc.name, doc.content));

        lista.appendChild(div);
    });
}

async function deletarDocumento(name) {
    try {
        await fetch('/delete-doc', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ filename: name })
        });
    } catch (e) { console.warn("Erro ao deletar no servidor:", e); }

    removeDocDoHistorico(name);
    carregarHistorico();

    if (currentDocName === name) {
        currentDocName     = "";
        currentFileContent = "";
        ocultarFileBar();
        limparChatLog();
    }
}

async function trocarDocumento(name, content) {
    currentDocName     = name;
    currentFileContent = content;

    try {
        const response = await fetch('/switch-context', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ content, filename: name })
        });
        const data = await response.json();

        if (data.ok) {
            exibirFileBar(name);
            atualizarIndicadorModo(data.modo || 'consulta');
            resetarPlacar();
            if (data.chat_history && data.chat_history.length > 0) {
                carregarChatHistory(data.chat_history);
            } else {
                limparChatLog();
            }
        }
    } catch { limparChatLog(); }
}

function carregarChatHistory(history) {
    limparChatLog();
    for (const msg of history) {
        if (msg.role === 'user')           appendChatSilent("USER",   msg.content);
        else if (msg.role === 'assistant') appendChatSilent("ADAMAS", msg.content);
    }
}

function appendChatSilent(author, text) {
    sessionLog.push({ author, text });
    const log = document.getElementById('chat-log');
    const div = document.createElement('div');
    div.className = "msg-container";
    const formatted = text.replace(/\*\*(.*?)\*\*/g, '<b>$1</b>');
    div.innerHTML = `<strong>[${author}]:</strong> ${formatted.replace(/\n/g, '<br>')}`;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
}

function limparChatLog() {
    document.getElementById('chat-log').innerHTML = "";
    sessionLog = [];
}

function appendChat(author, text) {
    sessionLog.push({ author, text });
    const log = document.getElementById('chat-log');
    const div = document.createElement('div');
    div.className = "msg-container";
    const formatted = text.replace(/\*\*(.*?)\*\*/g, '<b>$1</b>');
    div.innerHTML = `<strong>[${author}]:</strong> ${formatted.replace(/\n/g, '<br>')}`;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
    if (author === "ADAMAS") falarTexto(text);
}

function atualizarIndicadorModo(modo) {
    const el = document.getElementById('modo-indicator');
    if (!el) return;
    if (modo === 'sabatina') {
        el.textContent = '⚔ SABATINA';
        el.className   = 'modo-badge modo-sabatina';
    } else {
        el.textContent = '◈ CONSULTA';
        el.className   = 'modo-badge modo-consulta';
    }
}

function atualizarPlacar(placar) {
    const panel = document.getElementById('placar-panel');
    if (!panel) return;

    if (!placar) {
        panel.style.display = 'none';
        return;
    }

    panel.style.display = 'block';
    document.getElementById('placar-correto').textContent  = placar.correto;
    document.getElementById('placar-parcial').textContent  = placar.parcial;
    document.getElementById('placar-incorreto').textContent = placar.incorreto;
    document.getElementById('placar-total').textContent    = placar.total;
}

function resetarPlacar() {
    atualizarPlacar(null);
}

let recognition  = null;
let voiceAtivo   = false;  
let ttsAtivo     = true; 

function inicializarVoz() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

    if (SpeechRecognition) {
        recognition = new SpeechRecognition();
        recognition.lang           = 'pt-BR';
        recognition.continuous     = false;
        recognition.interimResults = false;

        recognition.onresult = (event) => {
            const transcript = event.results[0][0].transcript.trim();
            if (transcript) {
                document.getElementById('user-input').value = transcript;
                pararEscuta();
                setTimeout(() => sendMessage(), 300);
            }
        };

        recognition.onerror = (event) => {
            console.warn('Erro de reconhecimento:', event.error);
            pararEscuta();
            if (event.error === 'not-allowed') {
                appendChat("SISTEMA", "Permissão ao microfone negada. Verifique as configurações do navegador.");
            }
        };

        recognition.onend = () => {
            if (voiceAtivo) pararEscuta();
        };
    }

    if ('speechSynthesis' in window) {
        window.speechSynthesis.getVoices();
        window.speechSynthesis.onvoiceschanged = () => window.speechSynthesis.getVoices();
    }

    atualizarBotaoVoz(false);
}

function iniciarEscuta() {
    if (!recognition) {
        appendChat("SISTEMA", "Reconhecimento de voz não suportado. Use Chrome ou Edge.");
        return;
    }
    voiceAtivo = true;
    atualizarBotaoVoz(true);
    try { recognition.start(); } catch (e) { pararEscuta(); }
}

function pararEscuta() {
    voiceAtivo = false;
    atualizarBotaoVoz(false);
    try { recognition.stop(); } catch (e) {}
}

function toggleVoz() {
    if (voiceAtivo) pararEscuta();
    else iniciarEscuta();
}

function atualizarBotaoVoz(escutando) {
    const btn = document.getElementById('voice-btn');
    if (!btn) return;
    if (escutando) {
        btn.classList.add('voice-listening');
        btn.title = 'Parar escuta (Ctrl+M)';
    } else {
        btn.classList.remove('voice-listening');
        btn.title = 'Protocolo de Voz (Ctrl+M)';
    }
}

function falarTexto(texto) {
    if (!ttsAtivo || !('speechSynthesis' in window)) return;

    window.speechSynthesis.cancel();

    const limpo = texto
        .replace(/\[CORRETO\]/g, 'Correto.')
        .replace(/\[INCORRETO\]/g, 'Incorreto.')
        .replace(/\[PARCIALMENTE CORRETO\]/g, 'Parcialmente correto.')
        .replace(/\*\*(.*?)\*\*/g, '$1')
        .replace(/◈/g, '')
        .replace(/[\n\r]+/g, ' ')
        .trim();

    const utterance = new SpeechSynthesisUtterance(limpo);
    utterance.lang   = 'pt-BR';
    utterance.rate   = 1.0;
    utterance.pitch  = 1.0;
    utterance.volume = 1.0;

    const vozes = window.speechSynthesis.getVoices();
    const vozPT = vozes.find(v =>
        v.lang.startsWith('pt') &&
        (v.name.includes('Google') || v.name.includes('Microsoft'))
    ) || vozes.find(v => v.lang.startsWith('pt'));
    if (vozPT) utterance.voice = vozPT;

    window.speechSynthesis.speak(utterance);
}

function limparTudo() {
    document.getElementById('custom-modal').style.display = 'flex';
    document.getElementById('confirm-purge').onclick = async () => {
        fecharModal();
        await fetch('/reset', { method: 'POST' });
        localStorage.removeItem('adamas_docs');
        document.getElementById('history-list').innerHTML = "";
        limparChatLog();
        currentFileContent = "";
        currentDocName     = "";
        ocultarFileBar();
        atualizarIndicadorModo('consulta');
        window.speechSynthesis && window.speechSynthesis.cancel();
    };
}

function fecharModal() {
    document.getElementById('custom-modal').style.display = 'none';
}

function exibirFileBar(nome) {
    document.getElementById('afb-name').textContent = nome;
    document.getElementById('active-file-bar').style.display = 'flex';
}

function ocultarFileBar() {
    document.getElementById('active-file-bar').style.display = 'none';
    document.getElementById('afb-name').textContent = '—';
}

function showThinking() {
    thinkingEl = document.createElement('div');
    thinkingEl.className = "msg-container thinking-msg";
    thinkingEl.innerHTML = `<strong>[ADAMAS]:</strong> <span class="blink-cursor">_</span>`;
    document.getElementById('chat-log').appendChild(thinkingEl);
    document.getElementById('chat-log').scrollTop = 999999;
}

function hideThinking() {
    if (thinkingEl) { thinkingEl.remove(); thinkingEl = null; }
}

function exportChat() {
    if (sessionLog.length === 0) return;
    let out = `◈ ADAMAS — SESSÃO EXPORTADA\n`;
    out += `Documento: ${currentDocName || "nenhum"}\n`;
    out += `Data: ${new Date().toLocaleString('pt-BR')}\n`;
    out += `${'─'.repeat(42)}\n\n`;
    sessionLog.forEach(m => { out += `[${m.author}]\n${m.text}\n\n`; });
    const blob = new Blob([out], { type: 'text/plain; charset=utf-8' });
    const a    = document.createElement('a');
    a.href     = URL.createObjectURL(blob);
    a.download = `adamas_${currentDocName || "sessao"}_${Date.now()}.txt`;
    a.click();
}

// ══════════════════════════════════════════════════════════
// DASHBOARD DE DESEMPENHO HISTÓRICO
// ══════════════════════════════════════════════════════════

async function abrirDashboard() {
    const modal = document.getElementById('dashboard-modal');
    const body  = document.getElementById('dashboard-body');
    modal.style.display = 'flex';
    body.innerHTML = '<div class="dash-loading">◈ Carregando dados...</div>';

    try {
        const res  = await fetch('/dashboard');
        const data = await res.json();

        if (!data.ok || !data.dados.length) {
            body.innerHTML = '<div class="dash-empty">Nenhuma sabatina registrada ainda.<br>Complete uma sabatina para ver seu desempenho aqui.</div>';
            return;
        }

        body.innerHTML = '';
        data.dados.forEach(doc => renderDocDashboard(body, doc));

    } catch (e) {
        body.innerHTML = '<div class="dash-empty">Erro ao carregar dados.</div>';
    }
}

function renderDocDashboard(container, doc) {
    const section = document.createElement('div');
    section.className = 'dash-section';

    const header = document.createElement('div');
    header.className = 'dash-doc-header';
    header.innerHTML = `<span class="dash-doc-gem">◈</span><span class="dash-doc-nome">${doc.documento}</span><span class="dash-doc-count">${doc.sessoes.length} sessão(ões)</span>`;
    section.appendChild(header);

    if (doc.sessoes.length > 1) {
        const grafico = document.createElement('div');
        grafico.className = 'dash-grafico';
        grafico.innerHTML = '<div class="dash-grafico-label">Evolução de acertos (%)</div>';
        const barras = document.createElement('div');
        barras.className = 'dash-barras';
        doc.sessoes.forEach((s, i) => {
            const pct = s.percentual || 0;
            const cor = pct >= 80 ? '#00b44f' : pct >= 50 ? '#c89600' : '#ff2222';
            const barra = document.createElement('div');
            barra.className = 'dash-barra-wrap';
            barra.innerHTML = `
                <div class="dash-barra-col">
                    <div class="dash-barra-fill" style="height:${Math.max(pct, 4)}%;background:${cor};" title="${pct}%"></div>
                </div>
                <div class="dash-barra-label">${i + 1}</div>`;
            barras.appendChild(barra);
        });
        grafico.appendChild(barras);
        section.appendChild(grafico);
    }

    doc.sessoes.slice().reverse().forEach((s, i) => {
        const idx    = doc.sessoes.length - i;
        const pct    = s.percentual || 0;
        const corPct = pct >= 80 ? 'pct-solido' : pct >= 50 ? 'pct-parcial' : 'pct-insuf';
        const row    = document.createElement('div');
        row.className = 'dash-sessao';
        row.innerHTML = `
            <div class="dash-sessao-top">
                <span class="dash-sessao-num">Sessão ${idx}</span>
                <span class="dash-sessao-data">${s.data}</span>
                <span class="dash-pct ${corPct}">${pct}%</span>
            </div>
            <div class="dash-sessao-placar">
                <span class="dp-correto">✓ ${s.correto}</span>
                <span class="dp-parcial">~ ${s.parcial}</span>
                <span class="dp-incorreto">✗ ${s.incorreto}</span>
                <span class="dp-total">${s.total} perguntas</span>
            </div>`;

        if (s.detalhes && s.detalhes.length > 0) {
            const toggle = document.createElement('button');
            toggle.className = 'dash-toggle';
            toggle.textContent = 'Ver detalhes ▾';
            const detDiv = document.createElement('div');
            detDiv.className = 'dash-detalhes';
            detDiv.style.display = 'none';

            s.detalhes.forEach((d, di) => {
                const simbolo = d.classificacao === 'CORRETO' ? '✓' :
                                d.classificacao === 'PARCIALMENTE CORRETO' ? '~' : '✗';
                const cls = d.classificacao === 'CORRETO' ? 'det-c' :
                            d.classificacao === 'PARCIALMENTE CORRETO' ? 'det-p' : 'det-i';
                const item = document.createElement('div');
                item.className = `dash-det-item ${cls}`;
                item.innerHTML = `
                    <span class="det-num">${di + 1}.</span>
                    <div class="det-conteudo">
                        <div class="det-perg">${d.pergunta}</div>
                        <div class="det-resp">${simbolo} ${d.resposta}</div>
                    </div>`;
                detDiv.appendChild(item);
            });

            toggle.addEventListener('click', () => {
                const aberto = detDiv.style.display !== 'none';
                detDiv.style.display = aberto ? 'none' : 'block';
                toggle.textContent   = aberto ? 'Ver detalhes ▾' : 'Ocultar ▴';
            });

            row.appendChild(toggle);
            row.appendChild(detDiv);
        }

        section.appendChild(row);
    });

    container.appendChild(section);
}

document.getElementById('file-upload').onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    const response = await fetch('/upload', { method: 'POST', body: formData });
    const data     = await response.json();

    if (data.text) {
        currentFileContent = data.extracted_content;
        currentDocName     = file.name;
        exibirFileBar(file.name);
        atualizarIndicadorModo('consulta');

        if (data.chat_history && data.chat_history.length > 0) {
            carregarChatHistory(data.chat_history);
        } else {
            limparChatLog();
        }

        saveDocToHistorico(file.name, data.extracted_content);
        carregarHistorico();
    }
    e.target.value = "";
};

async function sendMessage() {
    const userInput = document.getElementById('user-input');
    const text      = userInput.value.trim();
    if (!text || isThinking) return;

    appendChat("USER", text);
    userInput.value = "";
    isThinking = true;

    const chatContainer = document.querySelector('.chat-container');
    chatContainer.classList.add('thinking');
    showThinking();

    try {
        const response = await fetch('/chat', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ message: text })
        });
        const data = await response.json();
        hideThinking();
        appendChat("ADAMAS", data.reply);
        if (data.modo) atualizarIndicadorModo(data.modo);
        if (data.placar !== undefined) atualizarPlacar(data.placar);
    } catch {
        hideThinking();
        appendChat("ADAMAS", "Falha crítica no núcleo.");
    } finally {
        isThinking = false;
        chatContainer.classList.remove('thinking');
    }
}

window.addEventListener('DOMContentLoaded', () => {
    init();
    carregarHistorico();
    inicializarVoz();

    document.getElementById('toggle-sidebar').addEventListener('click', () => {
        document.getElementById('sidebar').classList.toggle('collapsed');
        const hint      = document.getElementById('shortcuts-hint');
        const collapsed = document.getElementById('sidebar').classList.contains('collapsed');
        hint.style.opacity = collapsed ? '0' : '1';
        setTimeout(onWindowResize, 350);
    });

    document.getElementById('send-btn').addEventListener('click', sendMessage);
    document.getElementById('reset-btn').addEventListener('click', limparTudo);
    document.getElementById('export-btn').addEventListener('click', exportChat);
    document.getElementById('dashboard-btn').addEventListener('click', abrirDashboard);
    document.getElementById('dashboard-close').addEventListener('click', () => {
        document.getElementById('dashboard-modal').style.display = 'none';
    });

    document.getElementById('logout-btn').addEventListener('click', async () => {
        await fetch('/logout', { method: 'POST' });
        window.location.href = '/login';
    });
    document.getElementById('voice-btn').addEventListener('click', toggleVoz);

    document.getElementById('new-chat-btn').addEventListener('click', async () => {
        await fetch('/reset', { method: 'POST' });
        limparChatLog();
        currentDocName     = "";
        currentFileContent = "";
        ocultarFileBar();
        atualizarIndicadorModo('consulta');
        resetarPlacar();
        window.speechSynthesis && window.speechSynthesis.cancel();
    });

    document.getElementById('afb-clear-btn').addEventListener('click', async () => {
        await fetch('/clear-context', { method: 'POST' });
        currentFileContent = "";
        currentDocName     = "";
        ocultarFileBar();
        limparChatLog();
        atualizarIndicadorModo('consulta');
        window.speechSynthesis && window.speechSynthesis.cancel();
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') { fecharModal(); return; }
        if (!e.ctrlKey) return;
        const map = {
            'k': () => document.getElementById('new-chat-btn').click(),
            'u': () => document.getElementById('file-upload').click(),
            'e': () => exportChat(),
            'm': () => toggleVoz(),
            '/': () => appendChat("SISTEMA",
                "Atalhos disponíveis:\n" +
                "Ctrl+K — Nova sessão\n" +
                "Ctrl+U — Upload de arquivo\n" +
                "Ctrl+E — Exportar sessão\n" +
                "Ctrl+M — Voz on/off\n" +
                "Ctrl+/ — Esta ajuda\n" +
                "Esc    — Fechar modal"
            )
        };
        if (map[e.key]) { e.preventDefault(); map[e.key](); }
    });

    document.getElementById('user-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    window.addEventListener('resize', onWindowResize);
});