// State Management
let currentUser = { username: 'analyst', role: 'analyst', token: null };
let activeTab = 'chat';
let chartInstances = {};

// Switch Navigation Tabs
function switchTab(tabName) {
  activeTab = tabName;
  ['chat', 'traces', 'admin', 'eval'].forEach(tab => {
    const el = document.getElementById(`tab-${tab}`);
    const navBtn = document.getElementById(`nav-${tab}`);
    if (tab === tabName) {
      el.classList.remove('hidden');
      el.classList.add('flex');
      navBtn.className = "px-4 py-1.5 rounded-lg text-sm font-medium transition-all bg-indigo-600 text-white shadow-md";
    } else {
      el.classList.add('hidden');
      el.classList.remove('flex');
      navBtn.className = "px-4 py-1.5 rounded-lg text-sm font-medium text-slate-400 hover:text-white hover:bg-slate-700/50 transition-all";
    }
  });

  if (tabName === 'traces') {
    loadAgentTraces();
  } else if (tabName === 'admin') {
    loadAdminSchema();
    loadAdminLogs();
  }
}

// Toggle Role between Analyst and Admin
function toggleRole() {
  if (currentUser.role === 'analyst') {
    currentUser = { username: 'admin', role: 'admin', token: null };
  } else {
    currentUser = { username: 'analyst', role: 'analyst', token: null };
  }
  document.getElementById('user-display-name').innerText = currentUser.username.toUpperCase();
  document.getElementById('user-display-role').innerText = currentUser.role;
  alert(`Đã chuyển vai trò sang: ${currentUser.role.toUpperCase()}`);
}

// Fill Prompt from Suggestion Pill
function fillPrompt(text) {
  document.getElementById('prompt-input').value = text;
  document.getElementById('prompt-input').focus();
}

// Render User Message Bubble
function appendUserMessage(text) {
  const stream = document.getElementById('chat-stream');
  const msgDiv = document.createElement('div');
  msgDiv.className = 'flex items-start justify-end space-x-3 animate-fade-in';
  msgDiv.innerHTML = `
    <div class="bg-indigo-600 text-white rounded-2xl rounded-tr-none p-4 max-w-xl text-sm shadow-md">
      ${escapeHtml(text)}
    </div>
    <div class="w-8 h-8 rounded-lg bg-indigo-800 text-indigo-200 flex items-center justify-center flex-shrink-0 font-bold text-xs">
      ${currentUser.username.substring(0, 2).toUpperCase()}
    </div>
  `;
  stream.appendChild(msgDiv);
  stream.scrollTop = stream.scrollHeight;
}

// Handle Send Prompt
async function handleSendPrompt(e) {
  e.preventDefault();
  const input = document.getElementById('prompt-input');
  const text = input.value.trim();
  if (!text) return;

  input.value = '';
  appendUserMessage(text);

  // Append Loading Spinner Bubble
  const stream = document.getElementById('chat-stream');
  const loadingDiv = document.createElement('div');
  loadingDiv.id = 'loading-bubble';
  loadingDiv.className = 'flex items-start space-x-3 animate-fade-in';
  loadingDiv.innerHTML = `
    <div class="w-8 h-8 rounded-lg bg-indigo-600/30 text-indigo-400 flex items-center justify-center flex-shrink-0 border border-indigo-500/30">
      <i class="fa-solid fa-spinner fa-spin"></i>
    </div>
    <div class="bg-slate-800/80 rounded-2xl rounded-tl-none p-4 max-w-xl border border-slate-700 text-sm text-slate-300">
      Đang phân tích ý định (Planner) và sinh câu lệnh SQL (Generator)...
    </div>
  `;
  stream.appendChild(loadingDiv);
  stream.scrollTop = stream.scrollHeight;

  try {
    const res = await fetch('/api/v1/chat/ask', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        message: text,
        user_id: currentUser.username,
        role: currentUser.role
      })
    });

    const data = await res.json();
    document.getElementById('loading-bubble')?.remove();

    if (!res.ok) {
      appendErrorBubble(data.detail || data.error_message || 'Có lỗi xảy ra trong quá trình xử lý.');
      return;
    }

    if (data.status === 'need_clarification') {
      appendAmbiguityBubble(data);
    } else if (data.status === 'awaiting_approval') {
      appendHITLApprovalBubble(data);
    } else if (data.status === 'completed' || data.status === 'executed') {
      appendResultBubble(data);
    } else {
      appendErrorBubble(data.error_message || 'Có lỗi xảy ra trong quá trình xử lý.');
    }

  } catch (err) {
    document.getElementById('loading-bubble')?.remove();
    appendErrorBubble('Không thể kết nối đến server: ' + err.message);
  }
}

// Render Ambiguity / Clarification Question Bubble
function appendAmbiguityBubble(data) {
  const stream = document.getElementById('chat-stream');
  const div = document.createElement('div');
  div.className = 'flex items-start space-x-3 animate-fade-in';
  div.innerHTML = `
    <div class="w-8 h-8 rounded-lg bg-amber-600/30 text-amber-400 flex items-center justify-center flex-shrink-0 border border-amber-500/30">
      <i class="fa-solid fa-circle-question"></i>
    </div>
    <div class="bg-slate-800/90 rounded-2xl rounded-tl-none p-4 max-w-xl border border-amber-500/40 text-sm text-slate-200">
      <p class="font-semibold text-amber-400 mb-1"><i class="fa-solid fa-triangle-exclamation mr-1"></i>Câu hỏi chưa đủ thông tin</p>
      <p>${escapeHtml(data.ambiguity_question)}</p>
    </div>
  `;
  stream.appendChild(div);
  stream.scrollTop = stream.scrollHeight;
}

// Render HITL Approval Box (pause before SQL execution)
function appendHITLApprovalBubble(data) {
  const stream = document.getElementById('chat-stream');
  const div = document.createElement('div');
  div.id = `hitl-box-${data.thread_id}`;
  div.className = 'flex items-start space-x-3 animate-fade-in';

  const costLevel = data.cost_warning_level || 'green';
  const levelColors = {
    green: 'text-emerald-400 bg-emerald-950/60 border-emerald-800',
    yellow: 'text-amber-400 bg-amber-950/60 border-amber-800',
    red: 'text-rose-400 bg-rose-950/60 border-rose-800'
  };

  div.innerHTML = `
    <div class="w-8 h-8 rounded-lg bg-purple-600/30 text-purple-400 flex items-center justify-center flex-shrink-0 border border-purple-500/30">
      <i class="fa-solid fa-shield-halved"></i>
    </div>
    <div class="bg-slate-800/95 rounded-2xl rounded-tl-none p-5 max-w-2xl border border-indigo-500/50 shadow-xl space-y-4">
      <div class="flex items-center justify-between">
        <span class="text-xs font-bold text-indigo-400 uppercase tracking-wider flex items-center">
          <i class="fa-solid fa-code mr-1.5"></i>Xem trước SQL (HITL Governance)
        </span>
        <span class="text-xs px-2.5 py-1 rounded-full font-semibold border ${levelColors[costLevel] || levelColors.green}">
          <i class="fa-solid fa-gauge-high mr-1"></i>Cost: ${data.estimated_bytes ? (data.estimated_bytes / 1024).toFixed(1) : 0} KB
        </span>
      </div>

      <div class="relative">
        <textarea id="sql-input-${data.thread_id}" class="w-full bg-slate-950 text-emerald-400 font-mono text-xs p-3.5 rounded-xl border border-slate-700/80 focus:outline-none focus:border-indigo-500 min-h-[90px]">${escapeHtml(data.generated_sql || '')}</textarea>
        <div class="text-[10px] text-slate-500 mt-1">Chỉnh sửa SQL bên trên nếu cần trước khi phê duyệt.</div>
      </div>

      <div class="flex items-center justify-end space-x-3 pt-1">
        <button onclick="handleHITLAction('${data.thread_id}', 'reject')" class="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded-xl text-xs font-semibold transition-all">
          <i class="fa-solid fa-xmark mr-1.5"></i>Từ chối
        </button>
        <button onclick="handleHITLAction('${data.thread_id}', 'approve')" class="px-5 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-xs font-semibold shadow-md shadow-emerald-600/30 transition-all flex items-center">
          <i class="fa-solid fa-check mr-1.5"></i>Phê duyệt & Thực thi
        </button>
      </div>
    </div>
  `;
  stream.appendChild(div);
  stream.scrollTop = stream.scrollHeight;
}

// Handle User Decision on HITL Box
async function handleHITLAction(threadId, action) {
  const box = document.getElementById(`hitl-box-${threadId}`);
  const sqlInput = document.getElementById(`sql-input-${threadId}`);
  const modifiedSql = sqlInput ? sqlInput.value.trim() : null;

  if (box) {
    box.innerHTML = `
      <div class="w-8 h-8 rounded-lg bg-indigo-600/30 text-indigo-400 flex items-center justify-center flex-shrink-0 border border-indigo-500/30">
        <i class="fa-solid fa-spinner fa-spin"></i>
      </div>
      <div class="bg-slate-800/80 rounded-2xl rounded-tl-none p-4 max-w-xl border border-slate-700 text-sm text-slate-300">
        Đang xử lý ${action === 'approve' ? 'thực thi SQL (Executor)...' : 'hủy câu lệnh...'}
      </div>
    `;
  }

  try {
    const res = await fetch('/api/v1/chat/approve', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        thread_id: threadId,
        action: action,
        modified_sql: modifiedSql,
        user_id: currentUser.username
      })
    });

    const data = await res.json();
    box?.remove();

    if (!res.ok) {
      appendErrorBubble(data.detail || data.error_message || 'Thực thi SQL thất bại.');
      return;
    }

    if (data.status === 'executed' || data.status === 'completed') {
      appendResultBubble(data);
    } else if (data.status === 'rejected') {
      appendInfoBubble('Bạn đã từ chối thực thi câu lệnh SQL.');
    } else {
      appendErrorBubble(data.error_message || 'Thực thi SQL thất bại.');
    }

  } catch (err) {
    box?.remove();
    appendErrorBubble('Lỗi gửi phản hồi HITL: ' + err.message);
  }
}

// Render Results & Visualization Chart Bubble
function appendResultBubble(data) {
  const stream = document.getElementById('chat-stream');
  const div = document.createElement('div');
  const chartCanvasId = `chart-${Date.now()}`;
  div.className = 'flex items-start space-x-3 animate-fade-in';

  div.innerHTML = `
    <div class="w-8 h-8 rounded-lg bg-emerald-600/30 text-emerald-400 flex items-center justify-center flex-shrink-0 border border-emerald-500/30">
      <i class="fa-solid fa-chart-pie"></i>
    </div>
    <div class="bg-slate-800/90 rounded-2xl rounded-tl-none p-5 max-w-2xl border border-slate-700/80 space-y-4 shadow-xl">
      <!-- LLM Explanation -->
      <div class="text-sm text-slate-100 leading-relaxed font-normal">
        ${escapeHtml(data.explanation || 'Kết quả thực thi SQL:')}
      </div>

      <!-- Execution Stats Badge -->
      <div class="flex items-center space-x-3 text-xs text-slate-400 bg-slate-900/60 p-2.5 rounded-xl border border-slate-800">
        <span>📊 **${data.row_count}** dòng kết quả</span>
        <span>•</span>
        <span>⚡ ${data.execution_time_ms || 0} ms</span>
      </div>

      <!-- Render Chart Canvas if available -->
      ${data.chart_config && data.chart_config.type !== 'table' ? `
        <div class="bg-slate-950 p-4 rounded-xl border border-slate-800 relative h-64">
          <canvas id="${chartCanvasId}"></canvas>
        </div>
      ` : ''}

      <!-- Data Table View -->
      ${data.results && data.results.length > 0 ? `
        <div class="overflow-x-auto border border-slate-800 rounded-xl max-h-48 scrollbar-thin">
          <table class="w-full text-left text-xs text-slate-300">
            <thead class="bg-slate-900/90 text-slate-400 font-semibold uppercase sticky top-0">
              <tr>
                ${(data.columns || []).map(c => `<th class="p-2 border-b border-slate-800">${escapeHtml(c)}</th>`).join('')}
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-800/50">
              ${data.results.slice(0, 10).map(r => `
                <tr class="hover:bg-slate-800/40">
                  ${(data.columns || []).map(c => `<td class="p-2 font-mono">${escapeHtml(r[c])}</td>`).join('')}
                </tr>
              `).join('')}
            </tbody>
          </table>
          ${data.results.length > 10 ? `<div class="text-[10px] text-slate-500 p-1.5 text-center">Hiển thị 10 / ${data.results.length} dòng dữ liệu</div>` : ''}
        </div>
      ` : ''}
    </div>
  `;

  stream.appendChild(div);
  stream.scrollTop = stream.scrollHeight;

  // Initialize Chart.js if canvas exists
  if (data.chart_config && data.chart_config.type !== 'table' && data.results) {
    setTimeout(() => {
      renderChart(chartCanvasId, data.chart_config, data.results);
    }, 100);
  }
}

// Chart.js Generator
function renderChart(canvasId, config, rows) {
  const ctx = document.getElementById(canvasId);
  if (!ctx || !rows || rows.length === 0) return;

  const xAxisKey = config.xAxisKey || Object.keys(rows[0])[0];
  const seriesKeys = config.seriesKeys && config.seriesKeys.length > 0 ? config.seriesKeys : [Object.keys(rows[0])[1]];

  const labels = rows.map(r => String(r[xAxisKey]));
  const datasets = seriesKeys.map((key, idx) => ({
    label: key,
    data: rows.map(r => Number(r[key]) || 0),
    backgroundColor: idx === 0 ? 'rgba(99, 102, 241, 0.7)' : 'rgba(236, 72, 153, 0.7)',
    borderColor: idx === 0 ? '#6366f1' : '#ec4899',
    borderWidth: 1.5,
    borderRadius: 6
  }));

  const chartType = config.type === 'line' ? 'line' : (config.type === 'pie' ? 'pie' : 'bar');

  new Chart(ctx, {
    type: chartType,
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: '#94a3b8', font: { size: 11 } } }
      },
      scales: chartType !== 'pie' ? {
        x: { ticks: { color: '#64748b', font: { size: 10 } }, grid: { color: 'rgba(51,65,85,0.3)' } },
        y: { ticks: { color: '#64748b', font: { size: 10 } }, grid: { color: 'rgba(51,65,85,0.3)' } }
      } : {}
    }
  });
}

// Load Agent Traces for Traces Tab
async function loadAgentTraces() {
  try {
    const res = await fetch('/api/v1/traces');
    const data = await res.json();
    const tbody = document.getElementById('traces-table-body');
    if (!res.ok || !Array.isArray(data) || data.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" class="p-6 text-center text-slate-500">${res.ok ? 'Chưa có dữ liệu trace.' : escapeHtml(data.detail || 'Lỗi tải traces')}</td></tr>`;
      return;
    }

    tbody.innerHTML = data.map(t => `
      <tr class="hover:bg-slate-800/40">
        <td class="p-3 font-mono text-[11px] text-cyan-400">${t.trace_id.substring(0, 8)}...</td>
        <td class="p-3 font-medium text-slate-100 max-w-xs truncate" title="${escapeHtml(t.user_query)}">${escapeHtml(t.user_query)}</td>
        <td class="p-3 text-slate-300 font-mono">${t.total_duration_ms} ms</td>
        <td class="p-3 text-slate-400 font-mono">${t.total_llm_calls}</td>
        <td class="p-3">
          <span class="px-2 py-0.5 text-[10px] ${t.final_status === 'completed' || t.final_status === 'awaiting_approval' || t.final_status === 'executed' ? 'bg-emerald-950 text-emerald-300 border border-emerald-800' : 'bg-amber-950 text-amber-300'} rounded-full font-semibold">${t.final_status}</span>
        </td>
        <td class="p-3 font-semibold text-purple-400">${t.score !== null && t.score !== undefined ? t.score + '/100' : 'N/A'}</td>
        <td class="p-3">
          <button onclick="viewTraceDetail('${t.trace_id}')" class="px-2.5 py-1 text-[11px] bg-slate-800 hover:bg-slate-700 text-indigo-300 rounded border border-slate-700">
            <i class="fa-solid fa-eye mr-1"></i>Xem
          </button>
        </td>
      </tr>
    `).join('');
  } catch (err) {
    console.error('Agent Traces load error:', err);
  }
}

// View Trace Detail Modal / Alert
async function viewTraceDetail(traceId) {
  try {
    const res = await fetch(`/api/v1/traces/${traceId}`);
    const t = await res.json();
    if (!res.ok) {
      alert('Lỗi: ' + (t.detail || 'Không tìm thấy trace.'));
      return;
    }
    let detailText = `Trace ID: ${t.trace_id}\nQuery: ${t.user_query}\nStatus: ${t.final_status}\nDuration: ${t.total_duration_ms} ms\nLLM Calls: ${t.total_llm_calls}\n\nNodes Execution Timeline:\n`;
    
    if (t.nodes && t.nodes.length > 0) {
      t.nodes.forEach((n, idx) => {
        detailText += `${idx+1}. Node [${n.node_name.toUpperCase()}] - ${n.duration_ms} ms (${n.status})\n`;
      });
    }
    alert(detailText);
  } catch (err) {
    alert('Lỗi tải chi tiết trace: ' + err.message);
  }
}

// Load Schema Metadata for Admin Tab
async function loadAdminSchema() {
  try {
    const res = await fetch('/api/v1/admin/schema');
    const data = await res.json();
    const tbody = document.getElementById('schema-table-body');
    if (!res.ok || !Array.isArray(data)) {
      tbody.innerHTML = `<tr><td colspan="4" class="p-4 text-center text-slate-500">${escapeHtml(data.detail || 'Lỗi tải schema')}</td></tr>`;
      return;
    }
    tbody.innerHTML = data.map(item => `
      <tr class="hover:bg-slate-800/40">
        <td class="p-2.5 font-mono text-indigo-300 font-semibold">${escapeHtml(item.column_name)}</td>
        <td class="p-2.5 text-slate-400">${escapeHtml(item.data_type)}</td>
        <td class="p-2.5 text-slate-200">${escapeHtml(item.description_vi)}</td>
        <td class="p-2.5 text-slate-400 font-mono text-[11px]">${escapeHtml(item.sample_values || '')}</td>
      </tr>
    `).join('');
  } catch (err) {
    console.error('Schema load error:', err);
  }
}

// Load Audit Logs for Admin Tab
async function loadAdminLogs() {
  try {
    const res = await fetch('/api/v1/admin/logs');
    const data = await res.json();
    const tbody = document.getElementById('logs-table-body');
    if (!res.ok || !Array.isArray(data)) {
      tbody.innerHTML = `<tr><td colspan="7" class="p-4 text-center text-slate-500">${escapeHtml(data.detail || 'Lỗi tải logs')}</td></tr>`;
      return;
    }
    tbody.innerHTML = data.map(log => `
      <tr class="hover:bg-slate-800/40">
        <td class="p-2.5 font-mono text-slate-400">#${log.id}</td>
        <td class="p-2.5"><span class="px-2 py-0.5 text-[10px] bg-slate-800 text-indigo-300 rounded font-semibold">${escapeHtml(log.user_id)}</span></td>
        <td class="p-2.5 max-w-xs truncate" title="${escapeHtml(log.question)}">${escapeHtml(log.question)}</td>
        <td class="p-2.5 font-mono text-emerald-400 max-w-xs truncate" title="${escapeHtml(log.generated_sql || '')}">${escapeHtml(log.generated_sql || 'N/A')}</td>
        <td class="p-2.5"><span class="px-2 py-0.5 text-[10px] ${log.execution_status === 'SUCCESS' ? 'bg-emerald-950 text-emerald-300 border border-emerald-800' : 'bg-rose-950 text-rose-300'} rounded-full">${log.execution_status}</span></td>
        <td class="p-2.5">${log.row_count}</td>
        <td class="p-2.5 text-slate-400">${log.execution_time_ms} ms</td>
      </tr>
    `).join('');
  } catch (err) {
    console.error('Logs load error:', err);
  }
}

// Run Evaluation Benchmark
async function runEvaluation() {
  const btn = document.getElementById('btn-run-eval');
  btn.disabled = true;
  btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin mr-2"></i>Đang chạy 5D Benchmark...`;

  try {
    const res = await fetch('/api/v1/eval/run', { method: 'POST' });
    const data = await res.json();

    if (!res.ok || !data.details) {
      alert('Lỗi chạy eval benchmark: ' + (data.detail || 'Trả về dữ liệu không hợp lệ.'));
      return;
    }

    document.getElementById('eval-total').innerText = data.total_test_cases || 0;
    document.getElementById('eval-passed').innerText = data.passed_cases || 0;
    document.getElementById('eval-accuracy').innerText = `${data.execution_accuracy || 0}%`;
    if (document.getElementById('eval-avg-score')) {
      document.getElementById('eval-avg-score').innerText = `${data.average_score || 0}/100`;
    }

    const tbody = document.getElementById('eval-table-body');
    tbody.innerHTML = (data.details || []).map((item, idx) => `
      <tr class="hover:bg-slate-800/40">
        <td class="p-3 font-semibold text-slate-400">${idx + 1}</td>
        <td class="p-3 font-medium text-slate-100">${escapeHtml(item.question)}</td>
        <td class="p-3 font-mono text-[11px] text-slate-400 max-w-xs truncate" title="${escapeHtml(item.gold_sql)}">${escapeHtml(item.gold_sql)}</td>
        <td class="p-3 font-mono text-[11px] text-emerald-400 max-w-xs truncate" title="${escapeHtml(item.generated_sql)}">${escapeHtml(item.generated_sql)}</td>
        <td class="p-3 font-bold text-purple-400 font-mono">${item.composite_score !== undefined ? item.composite_score + '/100' : 'N/A'}</td>
        <td class="p-3">
          ${item.is_execution_matched ? 
            `<span class="px-2.5 py-1 text-xs bg-emerald-950 text-emerald-300 border border-emerald-800 rounded-full font-bold">✅ MATCH</span>` : 
            `<span class="px-2.5 py-1 text-xs bg-rose-950 text-rose-300 border border-rose-800 rounded-full font-bold">❌ FAIL</span>`
          }
        </td>
      </tr>
    `).join('');

  } catch (err) {
    alert('Lỗi chạy eval benchmark: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i class="fa-solid fa-play mr-2"></i>Chạy Benchmark Đánh Giá`;
  }
}

// Helper: Escape HTML
function escapeHtml(str) {
  if (typeof str !== 'string') return str;
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
}

// Helper: Append Error Bubble
function appendErrorBubble(msg) {
  const stream = document.getElementById('chat-stream');
  const div = document.createElement('div');
  div.className = 'flex items-start space-x-3 animate-fade-in';
  div.innerHTML = `
    <div class="w-8 h-8 rounded-lg bg-rose-600/30 text-rose-400 flex items-center justify-center flex-shrink-0 border border-rose-500/30">
      <i class="fa-solid fa-circle-exclamation"></i>
    </div>
    <div class="bg-slate-800/90 rounded-2xl rounded-tl-none p-4 max-w-xl border border-rose-500/40 text-sm text-rose-200">
      ${escapeHtml(msg)}
    </div>
  `;
  stream.appendChild(div);
  stream.scrollTop = stream.scrollHeight;
}

function appendInfoBubble(msg) {
  const stream = document.getElementById('chat-stream');
  const div = document.createElement('div');
  div.className = 'flex items-start space-x-3 animate-fade-in';
  div.innerHTML = `
    <div class="w-8 h-8 rounded-lg bg-slate-700 text-slate-300 flex items-center justify-center flex-shrink-0 border border-slate-600">
      <i class="fa-solid fa-info"></i>
    </div>
    <div class="bg-slate-800/80 rounded-2xl rounded-tl-none p-4 max-w-xl border border-slate-700 text-sm text-slate-300">
      ${escapeHtml(msg)}
    </div>
  `;
  stream.appendChild(div);
  stream.scrollTop = stream.scrollHeight;
}
