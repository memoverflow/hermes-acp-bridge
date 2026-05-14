// Dashboard real-time client
(function() {
    const WS_URL = `ws://${location.host}/ws`;
    let ws = null;
    let totalMessages = 0;

    const $status = document.getElementById('ws-status');
    const $connText = document.getElementById('connection-text');
    const $uptime = document.getElementById('uptime');
    const $sessions = document.getElementById('sessions-list');
    const $stream = document.getElementById('stream-output');
    const $timeline = document.getElementById('timeline');
    const $totalSessions = document.getElementById('total-sessions');
    const $totalMessages = document.getElementById('total-messages');
    const $totalEvents = document.getElementById('total-events');

    function connect() {
        ws = new WebSocket(WS_URL);

        ws.onopen = () => {
            $status.classList.add('connected');
            $connText.textContent = 'Connected';
        };

        ws.onclose = () => {
            $status.classList.remove('connected');
            $connText.textContent = 'Disconnected — reconnecting...';
            setTimeout(connect, 2000);
        };

        ws.onerror = () => {
            ws.close();
        };

        ws.onmessage = (evt) => {
            try {
                const msg = JSON.parse(evt.data);
                handleMessage(msg);
            } catch (e) {}
        };
    }

    function handleMessage(msg) {
        if (msg.type === 'init') {
            renderSessions(msg.data.sessions || []);
            $uptime.textContent = formatUptime(msg.data.uptime || 0);
            $totalEvents.textContent = msg.data.total_events || 0;
        } else if (msg.type === 'event') {
            addTimelineEvent(msg.data);
            totalMessages++;
            $totalMessages.textContent = totalMessages;
            $totalEvents.textContent = parseInt($totalEvents.textContent) + 1;
        } else if (msg.type === 'stream') {
            addStreamChunk(msg.data);
        } else if (msg.type === 'sessions_update') {
            renderSessions(msg.data || []);
        }
    }

    function renderSessions(sessions) {
        $totalSessions.textContent = sessions.length;
        if (sessions.length === 0) {
            $sessions.innerHTML = '<p class="empty">No active sessions</p>';
            return;
        }
        $sessions.innerHTML = sessions.map(s => `
            <div class="session-card">
                <span class="cli-badge ${s.cli}">${s.cli}</span>
                <span style="margin-left: 8px; color: ${s.status === 'running' ? 'var(--orange)' : 'var(--green)'}">${s.status}</span>
                <div class="session-id">${s.session_id}</div>
                <div class="session-stats">Messages: ${s.message_count} | CWD: ${s.cwd || '—'}</div>
            </div>
        `).join('');
    }

    function addStreamChunk(data) {
        const cls = data.update_type === 'agent_thought_chunk' ? 'thought' : 'message';
        const el = document.createElement('div');
        el.className = `stream-chunk ${cls}`;
        el.textContent = data.content;
        $stream.appendChild(el);
        $stream.scrollTop = $stream.scrollHeight;

        // Keep max 500 chunks
        while ($stream.children.length > 500) {
            $stream.removeChild($stream.firstChild);
        }
    }

    function addTimelineEvent(data) {
        const el = document.createElement('div');
        el.className = 'timeline-event';
        const time = new Date(data.time * 1000).toLocaleTimeString();
        el.innerHTML = `<span class="time">${time}</span>${data.type}: ${(data.request || data.content || '').substring(0, 80)}`;
        $timeline.insertBefore(el, $timeline.firstChild);

        while ($timeline.children.length > 100) {
            $timeline.removeChild($timeline.lastChild);
        }
    }

    function formatUptime(seconds) {
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);
        return `${h}h ${m}m ${s}s`;
    }

    // Update uptime every second
    setInterval(() => {
        const text = $uptime.textContent;
        if (text && text !== '—') {
            // Simple increment
        }
    }, 1000);

    connect();
})();
