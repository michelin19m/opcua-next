let ws = null;
let streaming = false;

// Connection functions
async function connect() {
    const endpoint = document.getElementById('endpoint').value;
    if (!endpoint) {
        showError('Please enter an endpoint');
        return;
    }

    try {
        const response = await fetch('/api/connect', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({endpoint: endpoint})
        });

        if (response.ok) {
            updateConnectionStatus(true);
            enableControls();
        } else {
            const error = await response.json();
            showError('Connection failed: ' + error.detail);
        }
    } catch (error) {
        showError('Connection error: ' + error.message);
    }
}

async function disconnect() {
    try {
        await fetch('/api/disconnect', {method: 'POST'});
        updateConnectionStatus(false);
        disableControls();
        if (ws) {
            ws.close();
            ws = null;
        }
    } catch (error) {
        showError('Disconnect error: ' + error.message);
    }
}

async function checkStatus() {
    try {
        const response = await fetch('/api/status');
        const status = await response.json();
        updateConnectionStatus(status.status === 'connected');
        if (status.status === 'connected') {
            enableControls();
        } else {
            disableControls();
        }
        await refreshServers();
    } catch (error) {
        console.error('Status check error:', error);
    }
}

function updateConnectionStatus(connected) {
    const statusDiv = document.getElementById('connectionStatus');
    if (connected) {
        statusDiv.className = 'status connected';
        statusDiv.textContent = 'Connected';
    } else {
        statusDiv.className = 'status disconnected';
        statusDiv.textContent = 'Disconnected';
    }
}

function enableControls() {
    document.getElementById('browseBtn').disabled = false;
    document.getElementById('readBtn').disabled = false;
    document.getElementById('writeBtn').disabled = false;
    document.getElementById('streamBtn').disabled = false;
    document.getElementById('saveTagsBtn').disabled = false;
    document.getElementById('trendBtn').disabled = false;
    document.getElementById('trendLastBtn').disabled = false;
}

function disableControls() {
    document.getElementById('browseBtn').disabled = true;
    document.getElementById('readBtn').disabled = true;
    document.getElementById('writeBtn').disabled = true;
    document.getElementById('streamBtn').disabled = true;
    document.getElementById('saveTagsBtn').disabled = true;
    document.getElementById('trendBtn').disabled = true;
    document.getElementById('trendLastBtn').disabled = true;
}

async function browseNodes() {
    try {
        const response = await fetch(`/api/browse`);
        const data = await response.json();
        displayNodes(data.nodes);
    } catch (error) {
        showError('Browse error: ' + error.message);
    }
}

function displayNodes(nodes, container = null, level = 0) {
    if (!container) {
        container = document.getElementById('nodeList');
        container.innerHTML = '';
        document.getElementById('nodeTree').style.display = 'block';
    }
    document.createElement('div');

    nodes.forEach(node => {
        const nodeWrapper = document.createElement('div');
        nodeWrapper.className = 'node-wrapper';
        nodeWrapper.style.marginLeft = (level * 10) + 'px';
        if (level > 0) {
            nodeWrapper.style.borderLeft = '1px solid #e0e7ef';
            nodeWrapper.style.paddingLeft = '12px';
        }

        const nodeDiv = document.createElement('div');
        nodeDiv.className = 'node-item';

        const contentWrapper = document.createElement('div');
        contentWrapper.style.display = 'flex';
        contentWrapper.style.alignItems = 'center';

        let toggleBtn = null;
        let childrenDiv = null;
        if (node.children && node.children.length > 0) {
            toggleBtn = document.createElement('span');
            toggleBtn.textContent = '▶';
            toggleBtn.className = 'expand';
            toggleBtn.style.cursor = 'pointer';
            toggleBtn.style.marginRight = '8px';

            childrenDiv = document.createElement('div');
            childrenDiv.style.display = 'none';

            displayNodes(node.children, childrenDiv, level + 1);

            nodeDiv.onclick = function() {
                if (childrenDiv.style.display === 'none') {
                    childrenDiv.style.display = 'block';
                    toggleBtn.textContent = '▼';
                } else {
                    childrenDiv.style.display = 'none';
                    toggleBtn.textContent = '▶';
                }
            };

            contentWrapper.appendChild(toggleBtn);
        }

        const labelDiv = document.createElement('span');
        labelDiv.className = 'node-label';
        labelDiv.innerHTML = `<strong>${node.browse_name}</strong> <span class="node-id">${node.nodeid}</span>`;
        if (node.value !== undefined) {
            labelDiv.innerHTML += ` <span class="node-value">${node.value}</span>`;
        }
        contentWrapper.appendChild(labelDiv);

        nodeDiv.appendChild(contentWrapper);

        if (node.value !== undefined) {
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.className = 'subscribe-checkbox';
            checkbox.value = node.nodeid;
            checkbox.style.marginLeft = 'auto';
            nodeDiv.appendChild(checkbox);
            nodeDiv.classList.add('node-leaf');
            if (!(node.children && node.children.length > 0)) {
                nodeDiv.onclick = function(e) {
                    if (e.target !== checkbox) {
                        checkbox.checked = !checkbox.checked;
                    }
                }
            }
        }

        nodeWrapper.appendChild(nodeDiv);

        container.appendChild(nodeWrapper);

        if (childrenDiv) {
            nodeWrapper.appendChild(childrenDiv);
        }
    });
}

// Read/Write functions
async function readNode() {
    const nodeId = document.getElementById('readNodeId').value;
    if (!nodeId) {
        showError('Please enter a node ID');
        return;
    }

    try {
        const response = await fetch('/api/read', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({node_id: nodeId})
        });

        const data = await response.json();
        document.getElementById('readResult').innerHTML = 
            `<div class="status connected">${nodeId}: ${JSON.stringify(data.value)}</div>`;
    } catch (error) {
        showError('Read error: ' + error.message);
    }
}

async function writeNode() {
    const nodeId = document.getElementById('readNodeId').value;
    const value = document.getElementById('writeValue').value;
    
    if (!nodeId || !value) {
        showError('Please enter both node ID and value');
        return;
    }

    try {
        const response = await fetch('/api/write', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({node_id: nodeId, value: value})
        });

        const data = await response.json();
        document.getElementById('readResult').innerHTML = 
            `<div class="status connected">Written: ${JSON.stringify(data.value)} to ${nodeId}</div>`;
    } catch (error) {
        showError('Write error: ' + error.message);
    }
}

// Data stream functions
function toggleDataStream() {
    if (!streaming) {
        startDataStream();
    } else {
        stopDataStream();
    }
}

function startDataStream() {
    // Collect checked node IDs
    const checked = Array.from(document.querySelectorAll('.subscribe-checkbox:checked'));
    const nodeIds = checked.map(cb => cb.value);

    if (nodeIds.length === 0) {
        showError('Please select at least one node to subscribe.');
        return;
    }

    if (ws) {
        ws.close();
    }

    ws = new WebSocket('ws://localhost:8000/ws?nodeids=' + encodeURIComponent(JSON.stringify(nodeIds)));

    ws.onopen = function() {
        streaming = true;
        document.getElementById('streamBtn').textContent = 'Stop Stream';
        document.getElementById('dataStream').style.display = 'block';
        document.getElementById('dataList').innerHTML = '<div>Connected to data stream...</div>';
    };

    ws.onmessage = function(event) {
        const data = JSON.parse(event.data);
        console.log('WebSocket message:', data);
        if (data.type === 'data_change') {
            addDataItem(data);
        }
    };

    ws.onclose = function() {
        streaming = false;
        document.getElementById('streamBtn').textContent = 'Start Stream';
    };
}

function stopDataStream() {
    if (ws) {
        ws.close();
        ws = null;
    }
    streaming = false;
    document.getElementById('streamBtn').textContent = 'Start Stream';
}

function addDataItem(data) {
    const dataList = document.getElementById('dataList');
    const div = document.createElement('div');
    div.className = 'data-item';
    div.textContent = `[${new Date(data.timestamp * 1000).toLocaleTimeString()}] ${data.node_id}: ${data.value}`;
    dataList.appendChild(div);
    
    // Keep only last 50 items
    while (dataList.children.length > 50) {
        dataList.removeChild(dataList.lastChild);
    }
}

function showError(message) {
    const errorDiv = document.createElement('div');
    errorDiv.className = 'error';
    errorDiv.textContent = message;
    document.body.insertBefore(errorDiv, document.body.firstChild);
    
    setTimeout(() => {
        errorDiv.remove();
    }, 5000);
}

// Server list
async function refreshServers() {
    const res = await fetch('/api/servers');
    const data = await res.json();
    const container = document.getElementById('savedServers');
    container.innerHTML = '';
    (data.servers || []).forEach(s => {
        const row = document.createElement('div');
        row.style.display = 'flex';
        row.style.border = '1px solid #eee';
        row.style.padding = '5px';
        row.style.alignItems = 'center';
        row.style.gap = '8px';
        const label = document.createElement('span');
        label.innerHTML = `<strong>${s.name || s.endpoint}</strong> <span class="node-id">${s.endpoint}</span>`;
        const conn = document.createElement('button');
        conn.textContent = 'Connect';
        conn.onclick = async () => {
            await fetch('/api/connect', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({endpoint: s.endpoint}) });
            updateConnectionStatus(true);
            enableControls();
        };
        const disconn = document.createElement('button');
        disconn.textContent = 'Disconnect';
        disconn.onclick = async () => { await disconnect(); };
        row.appendChild(label);
        row.appendChild(conn);
        row.appendChild(disconn);
        container.appendChild(row);
        // render saved tags as chips
        if (s.tags && s.tags.length) {
            const chips = document.createElement('div');
            chips.style.margin = '12px';
            // Fill trend selector with saved tags for the first server (or merge)
            const sel = document.getElementById('trendNodeId');
            sel.innerHTML = '';
            s.tags.forEach(t => {
                const chip = document.createElement('span');
                chip.style.padding = '2px 8px';
                chip.style.border = '1px solid #ddd';
                chip.style.borderRadius = '999px';
                chip.style.marginRight = '6px';
                chip.textContent = t.path;
                const opt = document.createElement('option');
                opt.value = t.node_id;
                opt.textContent = t.path;
                sel.appendChild(opt);
                const x = document.createElement('span');
                x.textContent = ' ×';
                x.style.cursor = 'pointer';
                x.onclick = async () => {
                    const qs = new URLSearchParams({ node_id: t.node_id });
                    await fetch(`/api/servers/${encodeURIComponent(s.id)}/tags?` + qs.toString(), { method: 'DELETE' });
                    await refreshServers();
                };
                chip.appendChild(x);
                chips.appendChild(chip);
            });
            container.appendChild(chips);
        }
    });
}

async function saveServer() {
    const endpoint = document.getElementById('endpoint').value;
    const name = document.getElementById('serverName').value;
    if (!endpoint) { showError('Enter endpoint'); return; }
    await fetch('/api/servers', { method: 'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({endpoint, name}) });
    await refreshServers();
}

// Save selected tags
async function saveSelectedTags() {
    const endpoint = document.getElementById('endpoint').value;
    const checked = Array.from(document.querySelectorAll('.subscribe-checkbox:checked'));
    if (!checked.length) { showError('Select at least one tag'); return; }
    for (const cb of checked) {
        const nodeId = cb.value;
        const path = cb.dataset.path || nodeId;
        await fetch('/api/tags', { method: 'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ server_id: endpoint, node_id: nodeId, path })});
    }
    await refreshServers();
}

// Historian controls
async function startHistorian() {
    const endpoint = document.getElementById('endpoint').value;
    const nodeIdsStr = document.getElementById('histNodeIds').value || '';
    const interval = parseInt(document.getElementById('histInterval').value || '1000', 10);
    const node_ids = nodeIdsStr.split(',').map(s => s.trim()).filter(Boolean);
    try {
        const res = await fetch('/api/historian/start', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ endpoint, node_ids, interval_ms: interval })
        });
        if (!res.ok) {
            const err = await res.json();
            showError('Historian start failed: ' + err.detail);
        }
    } catch (e) {
        showError('Historian start error: ' + e.message);
    }
}

async function stopHistorian() {
    try {
        await fetch('/api/historian/stop', { method: 'POST' });
    } catch (e) {
        showError('Historian stop error: ' + e.message);
    }
}

// Trends loader
async function loadTrends() {
    const nodeId = document.getElementById('trendNodeId').value;
    const start = document.getElementById('trendStart').value;
    const end = document.getElementById('trendEnd').value;
    const bucket = document.getElementById('trendBucket').value;
    if (!nodeId || !start || !end) {
        showError('Please fill node id, start and end');
        return;
    }
    const qs = new URLSearchParams({ node_id: nodeId, start, end });
    if (bucket) qs.append('bucket_seconds', bucket);
    try {
        const res = await fetch('/api/trends?' + qs.toString());
        const data = await res.json();
        const list = document.getElementById('trendList');
        list.innerHTML = '';
        (data.data || []).forEach(d => {
            const div = document.createElement('div');
            div.className = 'data-item';
            div.textContent = `${d.timestamp} - ${JSON.stringify(d.value)}`;
            list.appendChild(div);
        });
        document.getElementById('trendResult').style.display = 'block';
        // Clear plot when loading raw data
        const plotDiv = document.getElementById('trendPlot');
        if (plotDiv) { plotDiv.innerHTML = ''; }
    } catch (e) {
        showError('Trend load error: ' + e.message);
    }
}

async function loadLastN() {
    const nodeId = document.getElementById('trendNodeId').value;
    const n = parseInt(document.getElementById('trendLastN').value || '10', 10);
    if (!nodeId) { showError('Select a saved tag'); return; }
    document.getElementById('trendResult').style.display = 'block';
    try {
        const res = await fetch(`/api/trends/last?node_id=${encodeURIComponent(nodeId)}&n=${n}`);
        const j = await res.json();
        const xs = (j.data || []).map(d => d.timestamp);
        const ys = (j.data || []).map(d => {
            const v = d.value;
            const f = parseFloat(v);
            return Number.isFinite(f) ? f : null;
        });
        renderPlot(xs, ys, `${nodeId} (last ${n})`);
    } catch (e) {
        showError('Trend plot error: ' + e.message);
    }
}

function renderPlot(xs, ys, title) {
    const plotDiv = document.getElementById('trendPlot');
    const trace = {
        x: xs,
        y: ys,
        mode: 'lines+markers',
        name: 'OPC UA Value',
        hovertemplate: '%{x|%Y-%m-%d %H:%M:%S}<br>Value=%{y}<extra></extra>'
    };
    const layout = {
        title: title || 'Trend',
        xaxis: {
            title: 'Time',
            showgrid: true,
            gridcolor: 'rgba(200,200,200,0.3)'
        },
        yaxis: {
            title: 'Value',
            showgrid: true,
            gridcolor: 'rgba(200,200,200,0.3)'
        },
        template: 'plotly_white',
        legend: { orientation: 'h', yanchor: 'bottom', y: 1.02, xanchor: 'right', x: 1 }
    };
    Plotly.newPlot(plotDiv, [trace], layout, {responsive: true, displaylogo: false});
}

// Initialize
checkStatus();
setInterval(checkStatus, 5000); // Check status every 5 seconds