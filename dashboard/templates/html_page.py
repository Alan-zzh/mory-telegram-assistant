# -*- coding: utf-8 -*-
"""Dashboard前端HTML页面字符串"""

HTML_PAGE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mory Assistant - 私域可视化面板</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
/* ── 设计 Token（单一真相源，未来逐步替换硬编码值）── */
:root {
  --color-bg-primary: #0f0f1a;
  --color-bg-secondary: #1e1e2e;
  --color-bg-tertiary: #252540;
  --color-bg-card: #1e1e2e;
  --color-border-subtle: rgba(255, 255, 255, 0.06);
  --color-border-soft: rgba(255, 255, 255, 0.1);
  --color-text-primary: #e2e8f0;
  --color-text-secondary: #94a3b8;
  --color-text-muted: #6b7280;
  --color-text-heading: #fff;
  --color-accent-blue: #60a5fa;
  --color-accent-purple: #a78bfa;
  --color-accent-green: #10b981;
  --color-accent-orange: #f59e0b;
  --color-accent-blue-dark: #3b82f6;
  --gradient-primary: linear-gradient(135deg, #60a5fa, #a78bfa);
  --gradient-blue: linear-gradient(135deg, #60a5fa, #3b82f6);
  --gradient-bg: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 50%, #16213e 100%);
  --gradient-card: linear-gradient(135deg, #1e1e2e, #252540);
  --radius-sm: 10px;
  --radius-md: 12px;
  --radius-lg: 16px;
  --radius-xl: 24px;
  --shadow-card: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
  --font-mono: 'JetBrains Mono', monospace;
  --font-sans: 'Inter', system-ui, -apple-system, sans-serif;
}
* { font-family: 'Inter', system-ui, -apple-system, sans-serif; box-sizing: border-box; }
body { margin: 0; padding: 0; background: #0f0f1a; color: #e2e8f0; min-height: 100vh; }
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #1e1e2e; border-radius: 3px; }
::-webkit-scrollbar-thumb { background: #4a4a6a; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #6a6a8a; }

.login-container { min-height: 100vh; display: flex; align-items: center; justify-content: center; background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 50%, #16213e 100%); }
.login-box { background: rgba(30, 30, 46, 0.95); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 24px; padding: 48px; width: 100%; max-width: 420px; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5); }
.login-title { font-size: 28px; font-weight: 700; text-align: center; margin: 0 0 8px 0; background: linear-gradient(135deg, #60a5fa, #a78bfa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.login-subtitle { text-align: center; color: #94a3b8; margin: 0 0 8px 0; font-size: 14px; }
.login-desc { text-align: center; color: #64748b; margin: 0 0 32px 0; font-size: 12px; }
.input-group { margin-bottom: 20px; }
.input-group label { display: block; color: #94a3b8; font-size: 13px; font-weight: 500; margin-bottom: 8px; }
.input-field { width: 100%; padding: 14px 16px; background: #1e1e2e; border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 12px; color: #e2e8f0; font-size: 15px; transition: all 0.3s; }
.input-field:focus { outline: none; border-color: #60a5fa; box-shadow: 0 0 0 3px rgba(96, 165, 250, 0.2); }
.login-btn { width: 100%; padding: 14px; background: linear-gradient(135deg, #60a5fa, #3b82f6); border: none; border-radius: 12px; color: white; font-size: 15px; font-weight: 600; cursor: pointer; transition: all 0.3s; }
.login-btn:hover { transform: translateY(-2px); box-shadow: 0 10px 20px rgba(59, 130, 246, 0.3); }

.dashboard { display: flex; min-height: 100vh; }
.sidebar { width: 260px; background: #1e1e2e; border-right: 1px solid rgba(255, 255, 255, 0.06); display: flex; flex-direction: column; position: fixed; height: 100vh; z-index: 100; }
.sidebar-header { padding: 24px; border-bottom: 1px solid rgba(255, 255, 255, 0.06); }
.sidebar-logo { display: flex; align-items: center; gap: 12px; }
.sidebar-logo-icon { width: 40px; height: 40px; background: linear-gradient(135deg, #60a5fa, #a78bfa); border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 20px; }
.sidebar-logo-text h1 { font-size: 18px; font-weight: 700; color: #fff; margin: 0; }
.sidebar-logo-text span { font-size: 12px; color: #6b7280; }
.sidebar-nav { flex: 1; padding: 16px 12px; overflow-y: auto; }
.nav-section { margin-bottom: 24px; }
.nav-section-title { font-size: 11px; font-weight: 600; color: #6b7280; text-transform: uppercase; letter-spacing: 0.1em; padding: 0 12px; margin-bottom: 8px; }
.nav-item { display: flex; align-items: center; gap: 12px; padding: 12px; border-radius: 10px; color: #94a3b8; text-decoration: none; transition: all 0.2s; font-size: 14px; font-weight: 500; cursor: pointer; }
.nav-item:hover { background: rgba(255, 255, 255, 0.05); color: #e2e8f0; }
.nav-item.active { background: linear-gradient(135deg, rgba(96, 165, 250, 0.2), rgba(167, 139, 250, 0.2)); color: #60a5fa; border-left: 3px solid #60a5fa; }
.nav-item svg { width: 20px; height: 20px; stroke-width: 1.5; }

.main-content { flex: 1; margin-left: 260px; min-height: 100vh; }
.top-bar { background: rgba(30, 30, 46, 0.8); backdrop-filter: blur(10px); border-bottom: 1px solid rgba(255, 255, 255, 0.06); padding: 16px 32px; display: flex; align-items: center; justify-content: space-between; position: sticky; top: 0; z-index: 50; }
.top-bar-left { display: flex; align-items: center; gap: 16px; }
.page-title { font-size: 20px; font-weight: 600; color: #fff; }
.top-bar-right { display: flex; align-items: center; gap: 16px; }
.status-pill { display: flex; align-items: center; gap: 8px; padding: 8px 16px; background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 20px; font-size: 13px; color: #10b981; }
.status-dot { width: 8px; height: 8px; background: #10b981; border-radius: 50%; animation: pulse 2s infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
.icon-btn { width: 40px; height: 40px; background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 10px; display: flex; align-items: center; justify-content: center; color: #94a3b8; cursor: pointer; transition: all 0.2s; }
.icon-btn:hover { background: rgba(255, 255, 255, 0.1); color: #e2e8f0; }

.page-content { padding: 32px; }
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 32px; }
.page-header h2 { font-size: 24px; font-weight: 700; color: #fff; margin: 0; }
.page-header p { color: #6b7280; font-size: 14px; margin: 4px 0 0 0; }

.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 24px; margin-bottom: 32px; }
.stat-card { background: linear-gradient(135deg, #1e1e2e, #252540); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 16px; padding: 24px; position: relative; overflow: hidden; }
.stat-card::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px; background: linear-gradient(90deg, var(--accent-color), transparent); }
.stat-card.blue { --accent-color: #60a5fa; }
.stat-card.green { --accent-color: #10b981; }
.stat-card.purple { --accent-color: #a78bfa; }
.stat-card.orange { --accent-color: #f59e0b; }
.stat-icon { width: 48px; height: 48px; border-radius: 12px; display: flex; align-items: center; justify-content: center; margin-bottom: 16px; font-size: 24px; background: rgba(255, 255, 255, 0.05); }
.stat-value { font-size: 36px; font-weight: 700; color: #fff; font-family: 'JetBrains Mono', monospace; margin-bottom: 4px; line-height: 1; }
.stat-label { font-size: 14px; color: #6b7280; font-weight: 500; }

.charts-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 24px; margin-bottom: 32px; }
.chart-card { background: #1e1e2e; border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 16px; padding: 24px; }
.chart-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
.chart-title { font-size: 16px; font-weight: 600; color: #fff; }
.chart-container { height: 280px; position: relative; }

.data-table { width: 100%; border-collapse: collapse; }
.data-table th { text-align: left; padding: 12px 16px; font-size: 12px; font-weight: 600; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid rgba(255, 255, 255, 0.06); }
.data-table td { padding: 16px; font-size: 14px; color: #e2e8f0; border-bottom: 1px solid rgba(255, 255, 255, 0.03); }
.data-table tr:hover { background: rgba(255, 255, 255, 0.02); }
.data-table .user-cell { display: flex; align-items: center; gap: 12px; }
.user-avatar { width: 36px; height: 36px; border-radius: 50%; background: linear-gradient(135deg, #60a5fa, #a78bfa); display: flex; align-items: center; justify-content: center; font-weight: 600; font-size: 14px; }
.user-info .name { font-weight: 500; color: #fff; }
.user-info .uid { font-size: 12px; color: #6b7280; }

.badge { padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 500; }
.badge-success { background: rgba(16, 185, 129, 0.2); color: #10b981; }
.badge-warning { background: rgba(245, 158, 11, 0.2); color: #f59e0b; }
.badge-info { background: rgba(59, 130, 246, 0.2); color: #60a5fa; }

.btn { display: inline-flex; align-items: center; gap: 8px; padding: 10px 20px; border-radius: 10px; font-size: 14px; font-weight: 500; border: none; cursor: pointer; transition: all 0.2s; }
.btn-primary { background: linear-gradient(135deg, #60a5fa, #3b82f6); color: white; }
.btn-primary:hover { transform: translateY(-2px); box-shadow: 0 8px 16px rgba(59, 130, 246, 0.3); }
.btn-secondary { background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); color: #e2e8f0; }
.btn-secondary:hover { background: rgba(255, 255, 255, 0.1); }

.card { background: #1e1e2e; border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 16px; padding: 24px; }

.toast { position: fixed; top: 24px; right: 24px; padding: 16px 24px; border-radius: 12px; color: white; font-weight: 500; animation: slideIn 0.3s ease; box-shadow: 0 10px 25px rgba(0, 0, 0, 0.3); z-index: 9999; }
.toast-success { background: linear-gradient(135deg, #10b981, #059669); }
.toast-error { background: linear-gradient(135deg, #ef4444, #dc2626); }
.toast-info { background: linear-gradient(135deg, #60a5fa, #3b82f6); }
@keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }

.loading { display: flex; align-items: center; justify-content: center; padding: 60px; color: #6b7280; }
.loading::after { content: ''; width: 24px; height: 24px; border: 3px solid rgba(255, 255, 255, 0.1); border-top-color: #60a5fa; border-radius: 50%; animation: spin 0.8s linear infinite; margin-left: 12px; }
@keyframes spin { to { transform: rotate(360deg); } }

.empty-state { text-align: center; padding: 60px; color: #6b7280; }
.empty-state h3 { font-size: 18px; color: #94a3b8; margin-bottom: 8px; }

.search-box { display: flex; align-items: center; gap: 12px; background: #252540; border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 10px; padding: 8px 16px; margin-bottom: 24px; }
.search-box input { background: transparent; border: none; color: #e2e8f0; font-size: 14px; flex: 1; outline: none; }
.search-box input::placeholder { color: #6b7280; }
.search-box svg { color: #6b7280; width: 20px; height: 20px; }

.pagination { display: flex; align-items: center; justify-content: center; gap: 8px; margin-top: 32px; }
.pagination-btn { min-width: 40px; height: 40px; padding: 0 12px; background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px; color: #e2e8f0; cursor: pointer; transition: all 0.2s; display: flex; align-items: center; justify-content: center; }
.pagination-btn:hover { background: rgba(255, 255, 255, 0.1); }
.pagination-btn.active { background: #60a5fa; border-color: #60a5fa; color: white; }

@media (max-width: 1200px) { .charts-grid { grid-template-columns: 1fr; } }
@media (max-width: 768px) { .sidebar { transform: translateX(-100%); transition: transform 0.3s; } .sidebar.open { transform: translateX(0); } .main-content { margin-left: 0; } .stats-grid { grid-template-columns: 1fr; } .page-content { padding: 16px; } .top-bar { padding: 12px 16px; } }
</style>
</head>
<body>
<div id="app"></div>
<script>
const API_BASE = '';
let _csrfToken = '';  // CSRF Token（登录后从服务端获取）
let _userRole = 'admin';  // 当前用户角色：admin 或 viewer

async function loadVersion() {
  try {
    const d = await api('/api/bot/status');
    const el = document.getElementById('sidebarVersion');
    if (el) el.textContent = d.data.version || '?';
  } catch(e) {}
}

let currentPage = 'overview';
let currentUserPage = 1;
let searchQuery = '';
let sortField = 'last_active';
let sortOrder = 'desc';
let _chartData = null;

function formatTime(ts) {
  if (!ts) return 'N/A';
  const d = new Date(ts * 1000);
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function formatNumber(n) {
  if (n >= 10000) return (n / 10000).toFixed(1) + 'w';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
  return n;
}

function escHtml(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function showToast(msg, type = 'info') {
  const c = document.createElement('div');
  c.className = `toast toast-${type}`;
  c.textContent = msg;
  document.body.appendChild(c);
  setTimeout(() => c.remove(), 3000);
}

async function api(path, opts = {}) {
  try {
    // 自动为 POST/PUT/DELETE 请求附加 CSRF 头，防止 CSRF 校验失败
    const method = (opts.method || 'GET').toUpperCase();
    if (['POST', 'PUT', 'DELETE'].includes(method)) {
      opts.headers = { ...(opts.headers || {}), 'X-Requested-With': 'XMLHttpRequest' };
      // 附加 CSRF Token
      if (_csrfToken) {
        opts.headers['X-CSRF-Token'] = _csrfToken;
      }
      // 如果 body 是字符串（JSON），自动添加 Content-Type 头
      if (typeof opts.body === 'string' && !opts.headers['Content-Type']) {
        opts.headers['Content-Type'] = 'application/json';
      }
    }
    const res = await fetch(API_BASE + path, opts);
    const d = await res.json();
    if (!d.ok) throw new Error(d.msg || 'API Error');
    return d;
  } catch (e) {
    showToast(e.message, 'error');
    throw e;
  }
}

async function checkAuth() {
  try {
    const d = await api('/api/check');
    if (d.ok) _userRole = d.role || 'admin';
    return d.ok;
  } catch {
    return false;
  }
}

async function fetchCsrfToken() {
  try {
    const res = await fetch('/api/csrf-token', { credentials: 'same-origin' });
    const d = await res.json();
    if (d.ok && d.csrf_token) _csrfToken = d.csrf_token;
  } catch {}
}

async function doLogin() {
  const pw = document.getElementById('password').value;
  if (!pw) return;
  try {
    const d = await fetch('/api/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: JSON.stringify({ password: pw })
    });
    const r = await d.json();
    if (r.ok) {
      if (r.csrf_token) _csrfToken = r.csrf_token;
      if (r.role) _userRole = r.role;
      showToast('登录成功', 'success');
      window.location.reload();
    } else {
      showToast(r.msg, 'error');
    }
  } catch (e) {
    const msg = (e instanceof Response && e.status === 401) ? '密码错误，请重试'
              : (e instanceof Response && e.status === 403) ? '账号已锁定，联系超管'
              : '网络连接失败，请检查网络';
    showToast(msg, 'error');
  }
}

async function doLogout() {
  if (!confirm('确定要退出登录吗？')) return;
  try {
    await api('/api/logout', { method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
    window.location.reload();
  } catch {
    window.location.reload();
  }
}

async function loadStats() {
  try {
    const d = await api('/api/stats/overview');
    _chartData = d.data;
    renderStats(d.data);
  } catch (e) {
    console.error(e);
  }
}

function renderStats(data) {
  const setText = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
  setText('totalUsers', formatNumber(data.total_users || 0));
  setText('todayActive', formatNumber(data.today_active || 0));
  setText('weekActive', formatNumber(data.week_active || 0));
  setText('totalMsgs', formatNumber((data.total_group_msgs || 0) + (data.total_private_msgs || 0)));
  const vps = data.vps || {};
  const statusEl = document.getElementById('botStatus');
  const statusTextEl = document.getElementById('botStatusText');
  const statusDotEl = document.getElementById('statusDot');
  if (statusEl && statusTextEl && statusDotEl) {
    if (vps.bot_running) {
      statusEl.className = 'status-pill';
      statusTextEl.textContent = '运行中';
      statusDotEl.className = 'status-dot';
    } else {
      statusEl.className = 'status-pill';
      statusTextEl.textContent = '已停止';
      statusDotEl.className = 'status-dot';
    }
  }
  setText('botUptime', vps.uptime || 'N/A');
}

async function loadUsers(page = 1) {
  try {
    currentUserPage = page;
    const d = await api(`/api/stats/users?page=${page}&per_page=10&search=${encodeURIComponent(searchQuery)}&sort=${sortField}&order=${sortOrder}`);
    renderUserTable(d.data);
  } catch (e) {
    console.error(e);
  }
}

function renderUserTable(data) {
  const tb = document.getElementById('userTableBody');
  if (!tb) return;
  if (data.users.length === 0) {
    tb.innerHTML = '<tr><td colspan="7" class="empty-state"><h3>暂无用户数据</h3></td></tr>';
    return;
  }
  tb.innerHTML = data.users.map(u => `
    <tr>
      <td>
        <div class="user-cell">
          <div class="user-avatar">${escHtml((u.name || 'U')[0].toUpperCase())}</div>
          <div class="user-info">
            <div class="name">${escHtml(u.name || '未知用户')}</div>
            <div class="uid">UID: ${u.uid || u.user_id}</div>
          </div>
        </div>
      </td>
      <td>${u.level || 1}</td>
      <td>${u.points || 0}</td>
      <td>${u.group_messages || 0}</td>
      <td>${u.private_messages || 0}</td>
      <td><span class="badge ${getStatusClass(u.conversion_status)}">${escHtml(u.conversion_status || '新用户')}</span></td>
      <td>${formatTime(u.last_active)}</td>
    </tr>
  `).join('');
  renderPagination(data.pagination);
}

function getStatusClass(s) {
  if (s === 'paid' || s === 'vip') return 'badge-success';
  if (s === 'interested') return 'badge-info';
  if (s === 'cold') return 'badge-warning';
  return 'badge-info';
}

function renderPagination(p) {
  const pm = document.getElementById('pagination');
  if (!pm || !p) return;
  let html = '';
  for (let i = 1; i <= p.pages; i++) {
    html += `<button class="pagination-btn ${i === p.page ? 'active' : ''}" onclick="loadUsers(${i})">${i}</button>`;
  }
  pm.innerHTML = html;
}

function handleSearch() {
  searchQuery = document.getElementById('searchInput').value;
  loadUsers(1);
}

function handleSort(field) {
  if (sortField === field) {
    sortOrder = sortOrder === 'desc' ? 'asc' : 'desc';
  } else {
    sortField = field;
    sortOrder = 'desc';
  }
  loadUsers(1);
}

const _pageTitles = {
  overview: '数据概览', users: '用户管理', groups: '群组数据',
  status: '运行状态', models: '模型中心', tasks: '定时任务',
  groupmgr: '群管设置', feedback: '用户反馈', userprofile: '用户画像',
  attribution: '转化归因分析', funnel: '转化漏斗',
  modelperf: '大模型效能对比',
  config: '系统配置', reports: '运营报表', logs: '日志查看', helpcenter: '帮助中心',
  verification: '验证码配置', welcome: '欢迎定制', nightmode: '夜间模式',
  broadcasts: '定点播报', federation: '联邦封禁', emojimask: 'emoji面具',
  keywordtriggers: '关键词触发',
  // 设置面板完全体
  warning: '警告配置', slowmode: '慢速模式', usrreport: '举报配置',
  votekick: '投票踢人', antiflood: '反刷屏', antiraid: '反突袭',
  antidelete: '反撤回', nsfw: 'NSFW检测', blindbox: '盲盒配置',
  luckywheel: '转盘配置', redpacket: '红包配置', lottery: '抽奖配置',
  checkin: '签到配置', shop: '商城配置', coupon: '优惠券配置',
  tip: '打赏配置', dailyquest: '每日任务', achievement: '成就配置',
  pointsdecay: '积分衰减', afk: 'AFK配置', antichannel: '反频道转发',
  cas: 'CAS检查', cleanservice: '服务消息清理', autoreply: '自动回复',
  messagelocks: '消息锁', adspam: '广告防刷', inactiveclean: '不活跃清理',
  greeting: '问候配置', mystic: '传统文化播报', exchangerate: '汇率配置',
  visualdashboard: '可视化面板', language: '语言设置', spamaction: '广告动作',
  goodbye: '退群消息', rules: '群规配置', games: '游戏配置',
  aimodel: 'AI模型参数', botcore: 'Bot核心配置', pricing: '定价管理', persona: '人设编辑',
  replystyle: '风格样本审核'
};
function switchTab(tab) {
  document.querySelectorAll('.nav-item').forEach(t => t.classList.remove('active'));
  const navItem = document.querySelector(`.nav-item[onclick*="${tab}"]`);
  if (navItem) navItem.classList.add('active');
  currentPage = tab;
  const titleEl = document.querySelector('.page-title');
  if (titleEl) titleEl.textContent = _pageTitles[tab] || tab;
  renderPage();
}

function renderPage() {
  const content = document.getElementById('mainContent');
  if (!content) return;

  switch (currentPage) {
    case 'status':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>运行状态</h2>
            <p>Bot实时健康监控</p>
          </div>
          <button class="btn btn-secondary" onclick="loadBotStatus()">刷新</button>
        </div>
        <div id="statusContent" class="loading">加载中...</div>
      `;
      loadBotStatus();
      break;

    case 'models':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>模型中心</h2>
            <p>多模型池状态与路由管理</p>
          </div>
          <button class="btn btn-secondary" onclick="loadModels()">刷新</button>
        </div>
        <div id="modelsContent" class="loading">加载中...</div>
      `;
      loadModels();
      break;

    case 'tasks':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>定时任务</h2>
            <p>今日任务执行状态一览</p>
          </div>
          <button class="btn btn-secondary" onclick="loadTasks()">刷新</button>
        </div>
        <div id="tasksContent" class="loading">加载中...</div>
      `;
      loadTasks();
      break;

    case 'groupmgr':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>群管设置</h2>
            <p>敏感词/刷屏/禁言/欢迎语可视化管理</p>
          </div>
          <button class="btn btn-secondary" onclick="loadGroupMgr()">刷新</button>
        </div>
        <div id="groupMgrContent" class="loading">加载中...</div>
      `;
      loadGroupMgr();
      break;

    case 'feedback':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>用户反馈</h2>
            <p>👍👎满意度统计与反馈详情</p>
          </div>
          <button class="btn btn-secondary" onclick="loadFeedback()">刷新</button>
        </div>
        <div id="feedbackContent" class="loading">加载中...</div>
      `;
      loadFeedback();
      break;

    case 'helpcenter':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>帮助中心</h2>
            <p>使用手册与命令参考</p>
          </div>
        </div>
        <div id="helpContent" class="loading">加载中...</div>
      `;
      loadHelpCenter();
      break;

    case 'userprofile':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>用户画像</h2>
            <p>活跃趋势/分布/流失预警</p>
          </div>
          <button class="btn btn-secondary" onclick="loadUserProfile()">刷新</button>
        </div>
        <div id="userProfileContent" class="loading">加载中...</div>
      `;
      loadUserProfile();
      break;

    case 'overview':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>数据概览</h2>
            <p>实时监控核心指标</p>
          </div>
          <div style="display: flex; gap: 12px">
            <button class="btn btn-secondary" onclick="loadStats()">刷新数据</button>
          </div>
        </div>
        <div class="stats-grid">
          <div class="stat-card blue">
            <div class="stat-icon">👥</div>
            <div class="stat-value" id="totalUsers">-</div>
            <div class="stat-label">总用户数</div>
          </div>
          <div class="stat-card green">
            <div class="stat-icon">🟢</div>
            <div class="stat-value" id="todayActive">-</div>
            <div class="stat-label">今日活跃</div>
          </div>
          <div class="stat-card purple">
            <div class="stat-icon">📅</div>
            <div class="stat-value" id="weekActive">-</div>
            <div class="stat-label">7日活跃</div>
          </div>
          <div class="stat-card orange">
            <div class="stat-icon">💬</div>
            <div class="stat-value" id="totalMsgs">-</div>
            <div class="stat-label">消息总量（群+私聊）</div>
          </div>
        </div>
        <div class="charts-grid">
          <div class="chart-card">
            <div class="chart-header">
              <span class="chart-title">用户趋势（7天）</span>
            </div>
            <div class="chart-container">
              <canvas id="trendChart"></canvas>
            </div>
          </div>
          <div class="chart-card">
            <div class="chart-header">
              <span class="chart-title">时段分布</span>
            </div>
            <div class="chart-container">
              <canvas id="hourlyChart"></canvas>
            </div>
          </div>
        </div>
        <div class="charts-grid" style="margin-top: 0;">
          <div class="chart-card">
            <div class="chart-header">
              <span class="chart-title">转化漏斗</span>
            </div>
            <div class="chart-container">
              <canvas id="funnelChart"></canvas>
            </div>
          </div>
          <div class="chart-card">
            <div class="chart-header">
              <span class="chart-title">群组与频道</span>
            </div>
            <div id="groupChannelStats" style="padding: 8px 0;"></div>
          </div>
        </div>
      `;
      loadStats().then(() => { renderCharts(); renderFunnel(); renderGroupChannel(); });
      break;

    case 'users':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>用户管理</h2>
            <p>查看和管理用户数据</p>
          </div>
        </div>
        <div class="search-box">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/>
            <path d="M21 21l-4.35-4.35"/>
          </svg>
          <input type="text" id="searchInput" placeholder="搜索用户名或UID..." onkeyup="if(event.key === 'Enter') handleSearch()">
          <button class="btn btn-primary" onclick="handleSearch()">搜索</button>
        </div>
        <div class="card">
          <table class="data-table">
            <thead>
              <tr>
                <th onclick="handleSort('name')">用户</th>
                <th onclick="handleSort('level')">等级</th>
                <th>积分</th>
                <th onclick="handleSort('group_messages')">群消息</th>
                <th>私聊消息</th>
                <th>状态</th>
                <th>最后活跃</th>
              </tr>
            </thead>
            <tbody id="userTableBody">
              <tr>
                <td colspan="7" class="loading">加载中...</td>
              </tr>
            </tbody>
          </table>
          <div id="pagination" class="pagination"></div>
        </div>
      `;
      loadUsers();
      break;

    case 'groups':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>群组数据</h2>
            <p>群组活跃统计</p>
          </div>
          <button class="btn btn-secondary" onclick="loadGroups()">刷新</button>
        </div>
        <div id="groupContent" class="loading">加载中...</div>
      `;
      loadGroups();
      break;

    case 'config':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>系统配置</h2>
            <p>管理和配置系统参数</p>
          </div>
          <button class="btn btn-secondary" onclick="loadConfig()">刷新</button>
        </div>
        <div class="card" style="margin-bottom: 24px;">
          <h3 style="color: #fff; margin-bottom: 16px;">🔧 自然语言配置</h3>
          <div style="display: flex; gap: 12px; margin-bottom: 16px;">
            <input type="text" id="nlConfigInput" class="input-field" placeholder="例如：将早安问候时间改为8:30" style="flex: 1;">
            <button class="btn btn-primary" onclick="applyNlConfig()">应用</button>
          </div>
          <p style="color: #6b7280; font-size: 13px;">输入自然语言描述，系统自动解析并修改配置项</p>
        </div>
        <div class="card">
          <h3 style="color: #fff; margin-bottom: 16px;">📋 当前配置</h3>
          <div id="configContent" class="loading">加载中...</div>
        </div>
      `;
      loadConfig();
      break;

    case 'reports':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>运营报表</h2>
            <p>查看运营数据报告</p>
          </div>
        </div>
        <div class="card">
          <button class="btn btn-primary" onclick="downloadReport()">下载用户报表</button>
        </div>
      `;
      break;

    case 'logs':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>日志查看</h2>
            <p>查看对话和操作日志</p>
          </div>
        </div>
        <div class="search-box">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/>
            <path d="M21 21l-4.35-4.35"/>
          </svg>
          <input type="text" id="logSearchInput" placeholder="搜索日志关键词..." onkeyup="if(event.key === 'Enter') searchLogs()">
          <button class="btn btn-primary" onclick="searchLogs()">搜索</button>
        </div>
        <div class="card">
          <div id="logsContent" class="loading">加载中...</div>
        </div>
      `;
      loadLogs();
      break;

    case 'verification':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>验证码配置</h2>
            <p>入群验证码验证设置</p>
          </div>
          <button class="btn btn-secondary" onclick="loadVerification()">刷新</button>
        </div>
        <div id="verificationContent" class="loading">加载中...</div>
      `;
      loadVerification();
      break;

    case 'welcome':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>欢迎定制</h2>
            <p>入群欢迎/离群告别/群规配置</p>
          </div>
          <button class="btn btn-secondary" onclick="loadWelcomeConfig()">刷新</button>
        </div>
        <div id="welcomeContent" class="loading">加载中...</div>
      `;
      loadWelcomeConfig();
      break;

    case 'nightmode':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>夜间模式</h2>
            <p>夜间静默时段配置</p>
          </div>
          <button class="btn btn-secondary" onclick="loadNightMode()">刷新</button>
        </div>
        <div id="nightmodeContent" class="loading">加载中...</div>
      `;
      loadNightMode();
      break;

    case 'broadcasts':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>定点播报</h2>
            <p>定时播报内容管理</p>
          </div>
          <button class="btn btn-secondary" onclick="loadBroadcasts()">刷新</button>
        </div>
        <div id="broadcastsContent" class="loading">加载中...</div>
      `;
      loadBroadcasts();
      break;

    case 'broadcast-format':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>📝 播报格式（Rich）</h2>
            <p>v5.18.0 富文本升级 - Rich Messages / HTML / Auto 三种格式</p>
          </div>
          <button class="btn btn-secondary" onclick="loadBroadcastFormat()">刷新</button>
        </div>
        <div id="broadcastFormatContent" class="loading">加载中...</div>
      `;
      loadBroadcastFormat();
      break;

    case 'button-style':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>🎨 彩色按钮样式</h2>
            <p>v5.18.0 - 4 种按钮样式（default/danger/success/primary）+ Custom Emoji 图标</p>
          </div>
          <button class="btn btn-secondary" onclick="loadButtonStyle()">刷新</button>
        </div>
        <div id="buttonStyleContent" class="loading">加载中...</div>
      `;
      loadButtonStyle();
      break;

    case 'custom-emoji':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>😀 Custom Emoji 池</h2>
            <p>v5.18.0 - Premium Custom Emoji 配置（需 Bot 有 Custom Emoji 权限）</p>
          </div>
          <button class="btn btn-secondary" onclick="loadCustomEmojiPool()">刷新</button>
        </div>
        <div id="customEmojiContent" class="loading">加载中...</div>
      `;
      loadCustomEmojiPool();
      break;

    case 'user-profile':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>👤 用户画像</h2>
            <p>v5.18.0 - 个性化播报（VIP 专属 emoji / 等级感谢 / 兴趣匹配）</p>
          </div>
          <button class="btn btn-secondary" onclick="loadUserProfile()">刷新</button>
        </div>
        <div id="userProfileContent" class="loading">加载中...</div>
      `;
      loadUserProfile();
      break;

    case 'ab-test':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>🧪 A/B 测试</h2>
            <p>v5.18.0 - HTML vs Rich Message 转化率对比</p>
          </div>
          <button class="btn btn-secondary" onclick="loadABTest()">刷新</button>
        </div>
        <div id="abTestContent" class="loading">加载中...</div>
      `;
      loadABTest();
      break;

    case 'button-stats':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>📊 按钮点击统计</h2>
            <p>v5.18.0 - 不同样式按钮点击率追踪</p>
          </div>
          <button class="btn btn-secondary" onclick="loadButtonStats()">刷新</button>
        </div>
        <div id="buttonStatsContent" class="loading">加载中...</div>
      `;
      loadButtonStats();
      break;

    case 'federation':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>联邦封禁</h2>
            <p>跨群封禁用户管理</p>
          </div>
          <button class="btn btn-secondary" onclick="loadFederation()">刷新</button>
        </div>
        <div id="federationContent" class="loading">加载中...</div>
      `;
      loadFederation();
      break;

    case 'emojimask':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>emoji面具检测</h2>
            <p>入群用户名关键词自动禁言</p>
          </div>
          <button class="btn btn-secondary" onclick="loadEmojiMask()">刷新</button>
        </div>
        <div id="emojimaskContent" class="loading">加载中...</div>
      `;
      loadEmojiMask();
      break;

    case 'keywordtriggers':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>关键词触发</h2>
            <p>设置关键词自动回复规则（静态/智能/动作）</p>
          </div>
          <button class="btn btn-secondary" onclick="loadKeywordTriggers()">刷新</button>
        </div>
        <div id="keywordTriggersContent" class="loading">加载中...</div>
      `;
      loadKeywordTriggers();
      break;

    case 'warning':
      content.innerHTML = `
        <div class="page-header">
          <div><h2>警告配置</h2><p>用户违规警告阈值与处罚设置</p></div>
          <button class="btn btn-secondary" onclick="loadWarningConfig()">刷新</button>
        </div>
        <div id="warningContent" class="loading">加载中...</div>
      `;
      loadWarningConfig();
      break;

    case 'slowmode':
      content.innerHTML = `
        <div class="page-header">
          <div><h2>慢速模式</h2><p>群组消息发送间隔限制</p></div>
          <button class="btn btn-secondary" onclick="loadSlowmodeConfig()">刷新</button>
        </div>
        <div id="slowmodeContent" class="loading">加载中...</div>
      `;
      loadSlowmodeConfig();
      break;

    case 'report':
      content.innerHTML = `
        <div class="page-header">
          <div><h2>举报配置</h2><p>用户举报功能与冷却设置</p></div>
          <button class="btn btn-secondary" onclick="loadReportConfig()">刷新</button>
        </div>
        <div id="reportContent" class="loading">加载中...</div>
      `;
      loadReportConfig();
      break;

    case 'votekick':
      content.innerHTML = `
        <div class="page-header">
          <div><h2>投票踢人</h2><p>群成员投票踢人参数</p></div>
          <button class="btn btn-secondary" onclick="loadVotekickConfig()">刷新</button>
        </div>
        <div id="votekickContent" class="loading">加载中...</div>
      `;
      loadVotekickConfig();
      break;

    case 'antiflood':
      content.innerHTML = `
        <div class="page-header">
          <div><h2>反刷屏</h2><p>刷屏检测阈值与处罚</p></div>
          <button class="btn btn-secondary" onclick="loadAntifloodConfig()">刷新</button>
        </div>
        <div id="antifloodContent" class="loading">加载中...</div>
      `;
      loadAntifloodConfig();
      break;

    case 'antiraid':
      content.innerHTML = `
        <div class="page-header">
          <div><h2>反突袭</h2><p>批量进群突袭防护</p></div>
          <button class="btn btn-secondary" onclick="loadAntiraidConfig()">刷新</button>
        </div>
        <div id="antiraidContent" class="loading">加载中...</div>
      `;
      loadAntiraidConfig();
      break;

    case 'antidelete':
      content.innerHTML = `
        <div class="page-header">
          <div><h2>反撤回</h2><p>消息撤回拦截记录</p></div>
          <button class="btn btn-secondary" onclick="loadAntideleteConfig()">刷新</button>
        </div>
        <div id="antideleteContent" class="loading">加载中...</div>
      `;
      loadAntideleteConfig();
      break;

    case 'nsfw':
      content.innerHTML = `
        <div class="page-header">
          <div><h2>NSFW检测</h2><p>不适宜内容自动识别</p></div>
          <button class="btn btn-secondary" onclick="loadNsfwConfig()">刷新</button>
        </div>
        <div id="nsfwContent" class="loading">加载中...</div>
      `;
      loadNsfwConfig();
      break;

    case 'blindbox':
      content.innerHTML = `
        <div class="page-header">
          <div><h2>盲盒配置</h2><p>盲盒玩法参数设置</p></div>
          <button class="btn btn-secondary" onclick="loadBlindboxConfig()">刷新</button>
        </div>
        <div id="blindboxContent" class="loading">加载中...</div>
      `;
      loadBlindboxConfig();
      break;

    case 'luckywheel':
      content.innerHTML = `
        <div class="page-header">
          <div><h2>转盘配置</h2><p>幸运转盘参数设置</p></div>
          <button class="btn btn-secondary" onclick="loadLuckywheelConfig()">刷新</button>
        </div>
        <div id="luckywheelContent" class="loading">加载中...</div>
      `;
      loadLuckywheelConfig();
      break;

    case 'redpacket':
      content.innerHTML = `
        <div class="page-header">
          <div><h2>红包配置</h2><p>群红包金额范围</p></div>
          <button class="btn btn-secondary" onclick="loadRedpacketConfig()">刷新</button>
        </div>
        <div id="redpacketContent" class="loading">加载中...</div>
      `;
      loadRedpacketConfig();
      break;

    case 'lottery':
      content.innerHTML = `
        <div class="page-header">
          <div><h2>抽奖配置</h2><p>抽奖功能开关</p></div>
          <button class="btn btn-secondary" onclick="loadLotteryConfig()">刷新</button>
        </div>
        <div id="lotteryContent" class="loading">加载中...</div>
      `;
      loadLotteryConfig();
      break;

    case 'checkin':
      content.innerHTML = `
        <div class="page-header">
          <div><h2>签到配置</h2><p>签到积分与连续奖励</p></div>
          <button class="btn btn-secondary" onclick="loadCheckinConfig()">刷新</button>
        </div>
        <div id="checkinContent" class="loading">加载中...</div>
      `;
      loadCheckinConfig();
      break;

    case 'shop':
      content.innerHTML = `
        <div class="page-header">
          <div><h2>商城配置</h2><p>积分商城功能开关</p></div>
          <button class="btn btn-secondary" onclick="loadShopConfig()">刷新</button>
        </div>
        <div id="shopContent" class="loading">加载中...</div>
      `;
      loadShopConfig();
      break;

    case 'coupon':
      content.innerHTML = `
        <div class="page-header">
          <div><h2>优惠券配置</h2><p>优惠券功能开关</p></div>
          <button class="btn btn-secondary" onclick="loadCouponConfig()">刷新</button>
        </div>
        <div id="couponContent" class="loading">加载中...</div>
      `;
      loadCouponConfig();
      break;

    case 'tip':
      content.innerHTML = `
        <div class="page-header">
          <div><h2>打赏配置</h2><p>打赏功能与最低金额</p></div>
          <button class="btn btn-secondary" onclick="loadTipConfig()">刷新</button>
        </div>
        <div id="tipContent" class="loading">加载中...</div>
      `;
      loadTipConfig();
      break;

    case 'dailyquest':
      content.innerHTML = `
        <div class="page-header">
          <div><h2>每日任务</h2><p>每日任务功能开关</p></div>
          <button class="btn btn-secondary" onclick="loadDailyquestConfig()">刷新</button>
        </div>
        <div id="dailyquestContent" class="loading">加载中...</div>
      `;
      loadDailyquestConfig();
      break;

    case 'achievement':
      content.innerHTML = `
        <div class="page-header">
          <div><h2>成就配置</h2><p>成就系统开关</p></div>
          <button class="btn btn-secondary" onclick="loadAchievementConfig()">刷新</button>
        </div>
        <div id="achievementContent" class="loading">加载中...</div>
      `;
      loadAchievementConfig();
      break;

    case 'pointsdecay':
      content.innerHTML = `
        <div class="page-header">
          <div><h2>积分衰减</h2><p>积分自然衰减参数</p></div>
          <button class="btn btn-secondary" onclick="loadPointsdecayConfig()">刷新</button>
        </div>
        <div id="pointsdecayContent" class="loading">加载中...</div>
      `;
      loadPointsdecayConfig();
      break;

    case 'afk':
      content.innerHTML = `
        <div class="page-header">
          <div><h2>AFK配置</h2><p>离开状态检测</p></div>
          <button class="btn btn-secondary" onclick="loadAfkConfig()">刷新</button>
        </div>
        <div id="afkContent" class="loading">加载中...</div>
      `;
      loadAfkConfig();
      break;

    case 'antichannel':
      content.innerHTML = `
        <div class="page-header">
          <div><h2>反频道转发</h2><p>频道转发消息拦截</p></div>
          <button class="btn btn-secondary" onclick="loadAntichannelConfig()">刷新</button>
        </div>
        <div id="antichannelContent" class="loading">加载中...</div>
      `;
      loadAntichannelConfig();
      break;

    case 'cas':
      content.innerHTML = `
        <div class="page-header">
          <div><h2>CAS检查</h2><p>Combot反作弊系统</p></div>
          <button class="btn btn-secondary" onclick="loadCasConfig()">刷新</button>
        </div>
        <div id="casContent" class="loading">加载中...</div>
      `;
      loadCasConfig();
      break;

    case 'cleanservice':
      content.innerHTML = `
        <div class="page-header">
          <div><h2>服务消息清理</h2><p>自动清理系统消息</p></div>
          <button class="btn btn-secondary" onclick="loadCleanserviceConfig()">刷新</button>
        </div>
        <div id="cleanserviceContent" class="loading">加载中...</div>
      `;
      loadCleanserviceConfig();
      break;

    case 'autoreply':
      content.innerHTML = `
        <div class="page-header">
          <div><h2>自动回复</h2><p>群内自动回复开关</p></div>
          <button class="btn btn-secondary" onclick="loadAutoreplyConfig()">刷新</button>
        </div>
        <div id="autoreplyContent" class="loading">加载中...</div>
      `;
      loadAutoreplyConfig();
      break;

    case 'messagelocks':
      content.innerHTML = `<div class="page-header"><div><h2>消息锁</h2><p>限制群内消息类型</p></div></div><div id="messagelocksContent" class="loading">加载中...</div>`;
      loadMessageLocksConfig(); break;
    case 'adspam':
      content.innerHTML = `<div class="page-header"><div><h2>广告防刷</h2><p>广告检测与关键词过滤</p></div></div><div id="adspamContent" class="loading">加载中...</div>`;
      loadAdSpamConfig(); break;
    case 'inactiveclean':
      content.innerHTML = `<div class="page-header"><div><h2>不活跃清理</h2><p>自动踢出不活跃成员</p></div></div><div id="inactivecleanContent" class="loading">加载中...</div>`;
      loadInactiveCleanConfig(); break;
    case 'greeting':
      content.innerHTML = `<div class="page-header"><div><h2>问候配置</h2><p>早安/午安/晚安定时播报</p></div></div><div id="greetingContent" class="loading">加载中...</div>`;
      loadGreetingConfig(); break;
    case 'mystic':
      content.innerHTML = `<div class="page-header"><div><h2>传统文化播报</h2><p>早间真实黄历 · 午间三张塔罗 · 晚间易经一卦</p></div></div><div id="mysticContent" class="loading">加载中...</div>`;
      loadMysticConfig(); break;
    case 'exchangerate':
      content.innerHTML = `<div class="page-header"><div><h2>汇率配置</h2><p>实时U价查询设置</p></div></div><div id="exchangerateContent" class="loading">加载中...</div>`;
      loadExchangeRateConfig(); break;
    case 'visualdashboard':
      content.innerHTML = `<div class="page-header"><div><h2>可视化面板</h2><p>群数据可视化面板开关</p></div></div><div id="visualdashboardContent" class="loading">加载中...</div>`;
      loadVisualDashboardConfig(); break;
    case 'language':
      content.innerHTML = `<div class="page-header"><div><h2>语言设置</h2><p>界面与回复语言</p></div></div><div id="languageContent" class="loading">加载中...</div>`;
      loadLanguageConfig(); break;
    case 'spamaction':
      content.innerHTML = `<div class="page-header"><div><h2>广告动作</h2><p>刷屏检测后处罚方式</p></div></div><div id="spamactionContent" class="loading">加载中...</div>`;
      loadSpamActionConfig(); break;
    case 'goodbye':
      content.innerHTML = `<div class="page-header"><div><h2>退群消息</h2><p>成员退群时发送消息</p></div></div><div id="goodbyeContent" class="loading">加载中...</div>`;
      loadGoodbyeConfig(); break;
    case 'rules':
      content.innerHTML = `<div class="page-header"><div><h2>群规配置</h2><p>群规内容与触发方式</p></div></div><div id="rulesContent" class="loading">加载中...</div>`;
      loadRulesConfig(); break;
    case 'games':
      content.innerHTML = `<div class="page-header"><div><h2>游戏配置</h2><p>小游戏总开关</p></div></div><div id="gamesContent" class="loading">加载中...</div>`;
      loadGamesConfig(); break;
    case 'aimodel':
      content.innerHTML = `<div class="page-header"><div><h2>AI模型参数</h2><p>调整AI回复风格与行为</p></div></div><div id="aimodelContent" class="loading">加载中...</div>`;
      loadAiModelConfig(); break;
    case 'botcore':
      content.innerHTML = `<div class="page-header"><div><h2>Bot核心配置</h2><p>Bot名称与请求限制</p></div></div><div id="botcoreContent" class="loading">加载中...</div>`;
      loadBotCoreConfig(); break;
    case 'pricing':
      content.innerHTML = `<div class="page-header"><div><h2>定价管理</h2><p>商品价格与套餐配置</p></div></div><div id="pricingContent" class="loading">加载中...</div>`;
      loadPricingConfig(); break;
    case 'persona':
      content.innerHTML = `<div class="page-header"><div><h2>人设编辑</h2><p>系统提示词与知识库管理</p></div></div><div id="personaContent" class="loading">加载中...</div>`;
      loadPersonaConfig(); break;
    case 'replystyle':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>风格样本审核</h2>
            <p>人工审核的回复风格样本：通过 + 启用后才会注入 AI 提示词</p>
          </div>
          <div style="display:flex;gap:8px;align-items:center;">
            <select class="btn btn-secondary" onchange="setStyleStatus(this.value)" style="cursor:pointer;">
              <option value="">全部状态</option>
              <option value="pending">待审核</option>
              <option value="approved">已通过</option>
              <option value="rejected">已拒绝</option>
            </select>
            <select class="btn btn-secondary" onchange="setStyleScene(this.value)" style="cursor:pointer;">
              <option value="">全部场景</option>
              <option value="chat">chat · 聊天</option>
              <option value="greeting">greeting · 问候</option>
              <option value="engage">engage · 搭讪</option>
              <option value="faq">faq · FAQ</option>
              <option value="broadcast">broadcast · 播报</option>
            </select>
            <button class="btn btn-secondary" onclick="loadReplyStyleSamples()">刷新</button>
          </div>
        </div>
        <div class="card">
          <table class="data-table">
            <thead><tr><th>ID</th><th>标签</th><th>样本内容</th><th>状态</th><th>启用</th><th>创建人</th><th>操作</th></tr></thead>
            <tbody id="styleSampleBody"><tr><td colspan="7" class="empty-state"><h3>加载中...</h3></td></tr></tbody>
          </table>
        </div>
      `;
      loadReplyStyleSamples();
      break;
    case 'attribution':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>转化归因分析</h2>
            <p>Campaign / 时段 / 人设桶三维度归因可视化</p>
          </div>
          <button class="btn btn-secondary" onclick="loadAttributionReport()">刷新</button>
        </div>
        <div id="attributionContent" class="loading">加载中...</div>
      `;
      loadAttributionReport();
      break;

    case 'modelperf':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>大模型效能对比</h2>
            <p>阶段2-C 多模型路由 A/B 测试 - 转化率 / 延迟 / 成本对比</p>
          </div>
          <button class="btn btn-secondary" onclick="loadModelPerfReport()">刷新</button>
        </div>
        <div id="modelPerfContent" class="loading">加载中...</div>
      `;
      loadModelPerfReport();
      break;

    case 'funnel':
      content.innerHTML = `
        <div class="page-header">
          <div>
            <h2>转化漏斗</h2>
            <p>接触 → 感兴趣 → 加购 → 转化 全链路分析</p>
          </div>
          <div style="display:flex;gap:8px;">
            <select id="funnelDays" class="btn btn-secondary" onchange="loadFunnelPage()" style="cursor:pointer;">
              <option value="7">近 7 天</option>
              <option value="30">近 30 天</option>
            </select>
            <button class="btn btn-secondary" onclick="loadFunnelPage()">刷新</button>
          </div>
        </div>
        <div id="funnelStages" class="stats-grid"></div>
        <div class="charts-grid">
          <div class="chart-card">
            <div class="chart-header">
              <span class="chart-title">漏斗图</span>
            </div>
            <div class="chart-container" style="height:320px;">
              <canvas id="funnelPageChart"></canvas>
            </div>
          </div>
          <div class="chart-card">
            <div class="chart-header">
              <span class="chart-title">转化趋势</span>
            </div>
            <div class="chart-container" style="height:320px;">
              <canvas id="funnelTrendChart"></canvas>
            </div>
          </div>
        </div>
      `;
      loadFunnelPage();
      break;

    default:
      content.innerHTML = '<div class="empty-state"><h3>页面不存在</h3></div>';
  }
}

async function loadBotStatus() {
  try {
    const d = await api('/api/bot/status');
    const s = d.data;
    const el = document.getElementById('statusContent');
    if (!el) return;
    const runColor = s.bot_running ? '#10b981' : '#ef4444';
    const runText = s.bot_running ? '运行中' : '已停止';
    const runBg = s.bot_running ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.15)';
    const blCount = (s.blacklisted_models || []).length;
    el.innerHTML = `
      <div class="stats-grid">
        <div class="stat-card ${s.bot_running ? 'green' : ''}" style="border-left: 4px solid ${runColor};">
          <div class="stat-icon">${s.bot_running ? '🟢' : '🔴'}</div>
          <div class="stat-value" style="font-size: 28px; color: ${runColor};">${runText}</div>
          <div class="stat-label">Bot状态</div>
        </div>
        <div class="stat-card blue">
          <div class="stat-icon">📦</div>
          <div class="stat-value" style="font-size: 28px;">${escHtml(s.version)}</div>
          <div class="stat-label">版本号</div>
        </div>
        <div class="stat-card purple">
          <div class="stat-icon">🧠</div>
          <div class="stat-value" style="font-size: 18px;">${escHtml(s.current_model_name || '索引' + s.current_model_index)}</div>
          <div class="stat-label">当前模型</div>
        </div>
        <div class="stat-card orange">
          <div class="stat-icon">🚫</div>
          <div class="stat-value" style="font-size: 28px;">${blCount}</div>
          <div class="stat-label">黑名单模型</div>
        </div>
      </div>
      <div class="card" style="margin-top: 24px;">
        <h3 style="color: #fff; margin-bottom: 16px;">📊 详细信息</h3>
        <table class="data-table">
          <tbody>
            <tr><td style="font-weight:500; width:200px;">进程PID</td><td>${s.bot_pid || 'N/A'}</td></tr>
            <tr><td style="font-weight:500;">内存占用</td><td>${s.bot_memory || 'N/A'}</td></tr>
            <tr><td style="font-weight:500;">运行时长</td><td>${s.uptime || 'N/A'}</td></tr>
            <tr><td style="font-weight:500;">回复概率</td><td>${s.reply_chance}%</td></tr>
            <tr><td style="font-weight:500;">主群ID</td><td>${s.group_id || '未配置'}</td></tr>
            <tr><td style="font-weight:500;">管理员</td><td>${(s.admin_ids || []).join(', ') || '未配置'}</td></tr>
            ${blCount > 0 ? `<tr><td style="font-weight:500; color:#ef4444;">黑名单模型</td><td style="color:#ef4444;">${(s.blacklisted_models||[]).join(', ')}</td></tr>` : ''}
          </tbody>
        </table>
      </div>
    `;
  } catch(e) {
    console.error(e);
    const el = document.getElementById('statusContent');
    if (el) {
      el.className = 'empty-state';
      el.innerHTML = `<h3>加载失败</h3><p>${escHtml(e.message || '未知错误')}</p><button onclick="loadBotStatus()">重试</button>`;
    }
  }
}

async function loadModels() {
  try {
    const d = await api('/api/models/status');
    const data = d.data;
    const el = document.getElementById('modelsContent');
    if (!el) return;
    const routing = data._mode_routing || {};
    delete data._mode_routing;
    let html = '';
    const poolLabels = {
      llm: 'LLM文本', vision: '视觉', omni: '全模态',
      voice_tts: 'TTS语音', voice_asr: 'ASR识别', embedding: '向量',
      llm_light: '轻量路由', llm_standard: '标准路由', llm_premium: '旗舰路由'
    };
    for (const [poolName, models] of Object.entries(data)) {
      if (!Array.isArray(models)) continue;
      const label = poolLabels[poolName] || poolName;
      html += `
        <div class="card" style="margin-bottom: 20px;">
          <h3 style="color: #fff; margin-bottom: 16px;">${escHtml(label)} <span style="color:#6b7280; font-size:14px;">(${models.length}个模型)</span></h3>
          ${models.length === 0 ? '<p style="color:#6b7280;">暂无模型</p>' : `
          <table class="data-table">
            <thead><tr><th>模型名</th><th>描述</th><th>到期日</th><th>剩余天数</th><th>状态</th></tr></thead>
            <tbody>
              ${models.map(m => {
                const statusColor = m.blacklisted ? '#ef4444' : (m.days_left <= 7 ? '#f59e0b' : '#10b981');
                const statusBg = m.blacklisted ? 'rgba(239,68,68,0.2)' : (m.days_left <= 7 ? 'rgba(245,158,11,0.2)' : 'rgba(16,185,129,0.2)');
                return `<tr>
                  <td style="font-weight:500; font-family:'JetBrains Mono',monospace;">${escHtml(m.name)}</td>
                  <td>${escHtml(m.desc)}</td>
                  <td>${escHtml(m.expire)}</td>
                  <td style="color:${statusColor}; font-weight:600;">${m.days_left >= 9999 ? '永久' : m.days_left + '天'}</td>
                  <td><span class="badge" style="background:${statusBg}; color:${statusColor};">${m.status}</span></td>
                </tr>`;
              }).join('')}
            </tbody>
          </table>`}
        </div>
      `;
    }
    if (Object.keys(routing).length > 0) {
      html += `
        <div class="card">
          <h3 style="color: #fff; margin-bottom: 16px;">🔀 三层路由映射</h3>
          <table class="data-table">
            <thead><tr><th>模式(mode)</th><th>路由到</th></tr></thead>
            <tbody>
              ${Object.entries(routing).map(([mode, tier]) => `<tr><td style="font-weight:500;">${escHtml(mode)}</td><td><span class="badge badge-info">${escHtml(tier)}</span></td></tr>`).join('')}
            </tbody>
          </table>
        </div>
      `;
    }
    el.innerHTML = html || '<div class="empty-state"><h3>暂无模型配置</h3></div>';
  } catch(e) { console.error(e); }
}

async function loadTasks() {
  try {
    const d = await api('/api/tasks/status');
    const data = d.data;
    const el = document.getElementById('tasksContent');
    if (!el) return;
    const tasks = data.tasks || [];
    const doneCount = tasks.filter(t => t.done_today).length;
    el.innerHTML = `
      <div class="stats-grid" style="grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); margin-bottom: 24px;">
        <div class="stat-card green">
          <div class="stat-icon">✅</div>
          <div class="stat-value">${doneCount}</div>
          <div class="stat-label">今日已完成</div>
        </div>
        <div class="stat-card orange">
          <div class="stat-icon">⏳</div>
          <div class="stat-value">${tasks.length - doneCount}</div>
          <div class="stat-label">待执行/未到时间</div>
        </div>
        <div class="stat-card blue">
          <div class="stat-icon">📅</div>
          <div class="stat-value" style="font-size: 20px;">${escHtml(data.date)}</div>
          <div class="stat-label">统计日期</div>
        </div>
      </div>
      <div class="card">
        <table class="data-table">
          <thead><tr><th>任务名称</th><th>计划时间</th><th>今日状态</th><th>执行时间</th></tr></thead>
          <tbody>
            ${tasks.map(t => `
              <tr>
                <td style="font-weight:500;">${escHtml(t.name)}</td>
                <td>${escHtml(t.schedule)}</td>
                <td>${t.done_today
                  ? '<span class="badge badge-success">✅ 已完成</span>'
                  : '<span class="badge badge-warning">⏳ 未执行</span>'}</td>
                <td style="color: ${t.done_today ? '#10b981' : '#6b7280'};">${t.done_today ? t.exec_time : '-'}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  } catch(e) {
    console.error(e);
    const el = document.getElementById('tasksContent');
    if (el) {
      el.className = 'empty-state';
      el.innerHTML = `<h3>加载失败</h3><p>${escHtml(e.message || '未知错误')}</p><button onclick="loadTasks()">重试</button>`;
    }
  }
}

async function loadGroupMgr() {
  try {
    const d = await api('/api/group/settings');
    const s = d.data;
    const el = document.getElementById('groupMgrContent');
    if (!el) return;
    const bannedWords = (s.banned_words || []).join(', ');
    const hateKeywords = (s.hate_keywords || []).join(', ');
    const adKeywords = (s.ad_keywords || []).join(', ');
    const autoMuteNames = (s.auto_mute_names || []).join(', ');
    const spamLimit = s.spam_limit || {};
    const welcomeOn = s.welcome_msg !== false;
    el.innerHTML = `
      <div class="card" style="margin-bottom: 20px;">
        <h3 style="color:#fff; margin-bottom:16px;">🛡️ 敏感词管理</h3>
        <div style="margin-bottom:12px;">
          <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">违禁词（消息含这些词会被删除，逗号分隔）</label>
          <textarea id="bannedWordsInput" style="width:100%; min-height:60px; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px; resize:vertical;">${escHtml(bannedWords)}</textarea>
        </div>
        <div style="margin-bottom:12px;">
          <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">反感词（说这些词时Bot冷淡回应，逗号分隔）</label>
          <textarea id="hateKeywordsInput" style="width:100%; min-height:60px; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px; resize:vertical;">${escHtml(hateKeywords)}</textarea>
        </div>
        <div style="margin-bottom:12px;">
          <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">
            🆕 广告检测关键词（命中即删除+禁言，逗号分隔。留空使用内置默认词库）
          </label>
          <textarea id="adKeywordsInput" style="width:100%; min-height:60px; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px; resize:vertical;">${escHtml(adKeywords)}</textarea>
        </div>
        <button class="btn btn-primary" onclick="saveGroupList('BANNED_WORDS', 'bannedWordsInput')">保存违禁词</button>
        <button class="btn btn-secondary" onclick="saveGroupList('HATE_KEYWORDS', 'hateKeywordsInput')" style="margin-left:8px;">保存反感词</button>
        <button class="btn btn-secondary" onclick="saveGroupList('AD_KEYWORDS', 'adKeywordsInput')" style="margin-left:8px;">保存广告词</button>
      </div>

      <div class="card" style="margin-bottom: 20px;">
        <h3 style="color:#fff; margin-bottom:16px;">🚫 反刷屏与处罚</h3>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:12px;">
          <div>
            <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">
              每分钟消息上限
              <span style="color:#6b7280; font-size:11px;">（超出即触发禁言）</span>
            </label>
            <input id="spamMsgLimit" type="number" value="${spamLimit.messages_per_minute || 10}" style="width:100%; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px;">
          </div>
          <div>
            <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">
              刷屏自动禁言时长（分钟）
              <span style="color:#6b7280; font-size:11px;">（触发刷屏后自动禁言时长）</span>
            </label>
            <input id="spamBanMin" type="number" value="${spamLimit.ban_minutes || 5}" style="width:100%; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px;">
          </div>
        </div>
        <div style="margin-bottom:12px;">
          <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">
            手动封禁默认时长（分钟）
            <span style="color:#6b7280; font-size:11px;">（管理员手动ban时的默认值，不同于刷屏自动禁言）</span>
          </label>
          <input id="banDuration" type="number" value="${s.spam_ban_duration || 5}" style="width:200px; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px;">
        </div>
        <button class="btn btn-primary" onclick="saveSpamSettings()">保存刷屏设置</button>
      </div>

      <div class="card" style="margin-bottom: 20px;">
        <h3 style="color:#fff; margin-bottom:16px;">👋 入群欢迎</h3>
        <div style="margin-bottom:12px;">
          <label style="display:flex; align-items:center; gap:8px; color:#94a3b8; font-size:13px; margin-bottom:8px;">
            <input type="checkbox" id="welcomeOn" ${welcomeOn ? 'checked' : ''} style="width:18px; height:18px;">
            开启入群欢迎
          </label>
        </div>
        <div style="margin-bottom:12px;">
          <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">
            欢迎语内容
            <span style="color:#6b7280; font-size:11px;">（可用变量：{name}=用户名, {group}=群名）</span>
          </label>
          <textarea id="welcomeTextInput" style="width:100%; min-height:80px; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px; resize:vertical;">${escHtml(s.welcome_text || '')}</textarea>
        </div>
        <button class="btn btn-primary" onclick="saveWelcomeSettings()">保存欢迎设置</button>
      </div>

      <div class="card">
        <h3 style="color:#fff; margin-bottom:16px;">🔒 自动禁言关键词</h3>
        <p style="color:#6b7280; font-size:13px; margin-bottom:12px;">入群用户名含这些词会被自动永久禁言</p>
        <div style="margin-bottom:12px;">
          <textarea id="autoMuteNamesInput" style="width:100%; min-height:60px; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px; resize:vertical;">${escHtml(autoMuteNames)}</textarea>
        </div>
        <button class="btn btn-primary" onclick="saveGroupList('AUTO_MUTE_NAMES', 'autoMuteNamesInput')">保存禁言关键词</button>
      </div>
    `;
  } catch(e) { console.error(e); }
}

async function saveGroupList(key, inputId) {
  const raw = document.getElementById(inputId).value;
  const items = raw.split(/[,，、]/).map(s => s.trim()).filter(s => s);
  if (items.length === 0) {
    if (!confirm('确定要清空此列表吗？此操作不可撤销！')) return;
  }
  try {
    const r = await api('/api/group/settings/update', {
      method: 'POST',
      body: JSON.stringify({key, value: items})
    });
    showToast(r.ok ? r.msg : (r.msg || '保存失败'), r.ok ? 'success' : 'error');
  } catch(e) { showToast('保存失败', 'error'); }
}

async function saveSpamSettings() {
  const msgLimit = parseInt(document.getElementById('spamMsgLimit').value) || 10;
  const banMin = parseInt(document.getElementById('spamBanMin').value) || 5;
  const banDuration = parseInt(document.getElementById('banDuration').value) || 5;
  try {
    await api('/api/group/settings/update', {
      method: 'POST',
      body: JSON.stringify({key: 'SPAM_LIMIT', value: {messages_per_minute: msgLimit, ban_minutes: banMin}})
    });
    await api('/api/group/settings/update', {
      method: 'POST',
      body: JSON.stringify({key: 'BAN_DURATION_DEFAULT', value: banDuration})
    });
    showToast('刷屏设置已保存（⚠️ 需重启Bot或等待自动重载后生效）', 'success');
  } catch(e) { showToast('保存失败', 'error'); }
}

async function saveWelcomeSettings() {
  const welcomeOn = document.getElementById('welcomeOn').checked;
  const welcomeText = document.getElementById('welcomeTextInput').value;
  try {
    await api('/api/group/settings/update', {
      method: 'POST',
      body: JSON.stringify({key: 'WELCOME_MSG', value: welcomeOn})
    });
    await api('/api/group/settings/update', {
      method: 'POST',
      body: JSON.stringify({key: 'WELCOME_TEXT', value: welcomeText})
    });
    showToast('欢迎设置已保存（⚠️ 需重启Bot或等待自动重载后生效）', 'success');
  } catch(e) { showToast('保存失败', 'error'); }
}

async function loadFeedback() {
  try {
    const d = await api('/api/feedback/stats');
    const s = d.data;
    const el = document.getElementById('feedbackContent');
    if (!el) return;
    const rateColor = s.satisfaction_rate >= 80 ? '#10b981' : s.satisfaction_rate >= 50 ? '#f59e0b' : '#ef4444';
    const recent = s.recent || [];
    el.innerHTML = `
      <div class="stats-grid" style="margin-bottom:20px;">
        <div class="stat-card" style="border-left:4px solid #10b981;">
          <div class="stat-value" style="color:#10b981;">${s.like}</div>
          <div class="stat-label">👍 满意</div>
        </div>
        <div class="stat-card" style="border-left:4px solid #ef4444;">
          <div class="stat-value" style="color:#ef4444;">${s.dislike}</div>
          <div class="stat-label">👎 不满意</div>
        </div>
        <div class="stat-card" style="border-left:4px solid ${rateColor};">
          <div class="stat-value" style="color:${rateColor};">${s.satisfaction_rate}%</div>
          <div class="stat-label">满意度</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">${s.total}</div>
          <div class="stat-label">总反馈数</div>
        </div>
      </div>
      <div class="card">
        <h3 style="color:#fff; margin-bottom:16px;">最近反馈记录</h3>
        ${recent.length === 0 ? '<p style="color:#6b7280;">暂无反馈数据，Bot回复消息后用户可点击👍👎按钮</p>' : `
        <table class="data-table">
          <thead><tr><th>时间</th><th>用户ID</th><th>反馈</th><th>消息ID</th></tr></thead>
          <tbody>
            ${recent.map(r => {
              const dt = new Date(r.ts * 1000).toLocaleString('zh-CN');
              const fbEmoji = r.feedback === 'like' ? '👍 满意' : '👎 不满意';
              const fbColor = r.feedback === 'like' ? '#10b981' : '#ef4444';
              return `<tr><td>${dt}</td><td>${r.user_id}</td><td style="color:${fbColor};">${fbEmoji}</td><td>${r.bot_msg_id}</td></tr>`;
            }).join('')}
          </tbody>
        </table>`}
      </div>
    `;
  } catch(e) { console.error(e); }
}

async function loadHelpCenter() {
  try {
    const d = await api('/api/help/docs');
    const docs = d.data;
    const el = document.getElementById('helpContent');
    if (!el) return;
    let html = '';
    html += `<div class="card" style="margin-bottom:20px;">
      <h3 style="color:#fff; margin-bottom:16px;">👤 用户命令</h3>
      <table class="data-table"><thead><tr><th>命令</th><th>说明</th><th>示例</th></tr></thead><tbody>
      ${docs.user_commands.map(c => `<tr><td style="color:#60a5fa; font-weight:500;">${escHtml(c.cmd)}</td><td>${escHtml(c.desc)}</td><td style="color:#6b7280;">${escHtml(c.example)}</td></tr>`).join('')}
      </tbody></table></div>`;
    for (const sec of docs.admin_commands) {
      html += `<div class="card" style="margin-bottom:20px;">
        <h3 style="color:#fff; margin-bottom:16px;">🔐 ${escHtml(sec.section)}</h3>
        <table class="data-table"><thead><tr><th>命令</th><th>说明</th></tr></thead><tbody>
        ${sec.items.map(c => `<tr><td style="color:#60a5fa; font-weight:500;">${escHtml(c.cmd)}</td><td>${escHtml(c.desc)}</td></tr>`).join('')}
        </tbody></table></div>`;
    }
    html += `<div class="card">
      <h3 style="color:#fff; margin-bottom:16px;">📊 Dashboard页面指南</h3>
      <table class="data-table"><thead><tr><th>页面</th><th>说明</th></tr></thead><tbody>
      ${docs.dashboard_guide.map(g => `<tr><td style="color:#60a5fa; font-weight:500;">${escHtml(g.page)}</td><td>${escHtml(g.desc)}</td></tr>`).join('')}
      </tbody></table></div>`;
    el.innerHTML = html;
  } catch(e) { console.error(e); }
}

async function loadUserProfile() {
  try {
    const d = await api('/api/user/analytics');
    const s = d.data;
    const el = document.getElementById('userProfileContent');
    if (!el) return;
    const churnPct = s.total_users > 0 ? (s.churn_risk / s.total_users * 100).toFixed(1) : 0;
    const lostPct = s.total_users > 0 ? (s.lost / s.total_users * 100).toFixed(1) : 0;
    const churnColor = churnPct > 30 ? '#ef4444' : churnPct > 15 ? '#f59e0b' : '#10b981';
    el.innerHTML = `
      <div class="stats-grid" style="margin-bottom:20px;">
        <div class="stat-card">
          <div class="stat-value">${s.total_users}</div>
          <div class="stat-label">总用户数</div>
        </div>
        <div class="stat-card green">
          <div class="stat-value" style="color:#10b981;">${s.dau}</div>
          <div class="stat-label">日活(DAU)</div>
        </div>
        <div class="stat-card">
          <div class="stat-value" style="color:#60a5fa;">${s.wau}</div>
          <div class="stat-label">周活(WAU)</div>
        </div>
        <div class="stat-card">
          <div class="stat-value" style="color:#a78bfa;">${s.mau}</div>
          <div class="stat-label">月活(MAU)</div>
        </div>
      </div>
      <div class="stats-grid" style="margin-bottom:20px;">
        <div class="stat-card" style="border-left:4px solid ${churnColor};">
          <div class="stat-value" style="color:${churnColor};">${s.churn_risk} (${churnPct}%)</div>
          <div class="stat-label">⚠️ 流失预警(14天未活跃)</div>
        </div>
        <div class="stat-card" style="border-left:4px solid #ef4444;">
          <div class="stat-value" style="color:#ef4444;">${s.lost} (${lostPct}%)</div>
          <div class="stat-label">🔴 已流失(30天未活跃)</div>
        </div>
      </div>
      <div class="card" style="margin-bottom:20px;">
        <h3 style="color:#fff; margin-bottom:16px;">📈 7日DAU趋势</h3>
        <div style="display:flex; align-items:flex-end; gap:8px; height:120px; padding:0 8px;">
          ${(s.dau_trend || []).map(t => {
            const maxDau = Math.max(...(s.dau_trend || []).map(x => x.dau), 1);
            const h = Math.max(t.dau / maxDau * 100, 4);
            const dayLabel = t.date.substring(5);
            return `<div style="flex:1; display:flex; flex-direction:column; align-items:center; gap:4px;">
              <span style="color:#e2e8f0; font-size:11px;">${t.dau}</span>
              <div style="width:100%; height:${h}px; background:linear-gradient(180deg,#60a5fa,#3b82f6); border-radius:4px 4px 0 0;"></div>
              <span style="color:#6b7280; font-size:10px;">${dayLabel}</span>
            </div>`;
          }).join('')}
        </div>
      </div>
      <div class="card">
        <h3 style="color:#fff; margin-bottom:16px;">🏆 活跃排行榜 TOP10</h3>
        <table class="data-table">
          <thead><tr><th>#</th><th>用户</th><th>消息数</th><th>最后活跃</th></tr></thead>
          <tbody>
            ${(s.top_users || []).map((u, i) => {
              const dt = u.last_active ? new Date(u.last_active * 1000).toLocaleString('zh-CN') : '未知';
              const medal = i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : `${i+1}`;
              return `<tr><td>${medal}</td><td>${escHtml(u.name)}<span style="color:#6b7280; font-size:11px;"> (${u.uid})</span></td><td>${u.messages}</td><td style="color:#6b7280;">${dt}</td></tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>
    `;
  } catch(e) { console.error(e); }
}

function renderCharts() {
  const ctx1 = document.getElementById('trendChart');
  const ctx2 = document.getElementById('hourlyChart');
  const data = _chartData || {};
  const trend = data.online_trend || [];
  const hourly = data.hourly_dist || {};

  if (ctx1 && trend.length > 0) {
    const labels = trend.map(t => t.date);
    const values = trend.map(t => t.value);
    new Chart(ctx1, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: '新增用户',
          data: values,
          borderColor: '#60a5fa',
          backgroundColor: 'rgba(96, 165, 250, 0.1)',
          fill: true,
          tension: 0.4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: '#6b7280' }, grid: { color: 'rgba(255,255,255,0.05)' } },
          y: { ticks: { color: '#6b7280' }, grid: { color: 'rgba(255,255,255,0.05)' } }
        }
      }
    });
  } else if (ctx1) {
    ctx1.parentElement.innerHTML = '<div class="empty-state"><h3>暂无趋势数据</h3></div>';
  }

  if (ctx2) {
    const hourLabels = [];
    const hourValues = [];
    for (let h = 0; h < 24; h++) {
      hourLabels.push(String(h).padStart(2, '0') + ':00');
      hourValues.push(hourly[h] || 0);
    }
    new Chart(ctx2, {
      type: 'bar',
      data: {
        labels: hourLabels,
        datasets: [{
          label: '活跃用户',
          data: hourValues,
          backgroundColor: 'rgba(167, 139, 250, 0.8)',
          borderRadius: 8
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: '#6b7280', maxTicksLimit: 12 }, grid: { display: false } },
          y: { ticks: { color: '#6b7280' }, grid: { color: 'rgba(255,255,255,0.05)' } }
        }
      }
    });
  }
}

function renderFunnel() {
  const ctx = document.getElementById('funnelChart');
  if (!ctx || !_chartData) return;
  const funnel = _chartData.conversion_funnel || {};
  const labels = Object.keys(funnel);
  const values = Object.values(funnel);
  if (labels.length === 0) {
    ctx.parentElement.innerHTML = '<div class="empty-state"><h3>暂无转化数据</h3></div>';
    return;
  }
  const colors = ['#60a5fa', '#a78bfa', '#f59e0b', '#10b981', '#ef4444', '#6366f1'];
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: '用户数',
        data: values,
        backgroundColor: labels.map((_, i) => colors[i % colors.length] + 'cc'),
        borderRadius: 8
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: '#6b7280' }, grid: { color: 'rgba(255,255,255,0.05)' } },
        y: { ticks: { color: '#e2e8f0', font: { size: 12 } }, grid: { display: false } }
      }
    }
  });
}

function renderGroupChannel() {
  const el = document.getElementById('groupChannelStats');
  if (!el || !_chartData) return;
  const gs = _chartData.group_stats || {};
  const cs = _chartData.channel_stats || {};
  el.innerHTML = `
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
      <div style="background: rgba(96,165,250,0.08); border-radius: 12px; padding: 16px;">
        <div style="font-size: 13px; color: #6b7280; margin-bottom: 8px;">群组（7日）</div>
        <div style="display: flex; gap: 16px; flex-wrap: wrap;">
          <div><span style="font-size: 20px; font-weight: 700; color: #10b981;">+${gs.week_joined || 0}</span><div style="font-size: 11px; color: #6b7280;">入群</div></div>
          <div><span style="font-size: 20px; font-weight: 700; color: #ef4444;">-${gs.week_left || 0}</span><div style="font-size: 11px; color: #6b7280;">离群</div></div>
          <div><span style="font-size: 20px; font-weight: 700; color: ${(gs.week_net || 0) >= 0 ? '#60a5fa' : '#ef4444'};">${(gs.week_net || 0) >= 0 ? '+' : ''}${gs.week_net || 0}</span><div style="font-size: 11px; color: #6b7280;">净增</div></div>
        </div>
      </div>
      <div style="background: rgba(167,139,250,0.08); border-radius: 12px; padding: 16px;">
        <div style="font-size: 13px; color: #6b7280; margin-bottom: 8px;">频道</div>
        <div style="display: flex; gap: 16px; flex-wrap: wrap;">
          <div><span style="font-size: 20px; font-weight: 700; color: #a78bfa;">${cs.total_posts || 0}</span><div style="font-size: 11px; color: #6b7280;">帖子数</div></div>
          <div><span style="font-size: 20px; font-weight: 700; color: #f59e0b;">${cs.total_views || 0}</span><div style="font-size: 11px; color: #6b7280;">总浏览</div></div>
          <div><span style="font-size: 20px; font-weight: 700; color: #60a5fa;">${cs.avg_views || 0}</span><div style="font-size: 11px; color: #6b7280;">均浏览</div></div>
        </div>
      </div>
    </div>
  `;
}

async function loadGroups() {
  try {
    const d = await api('/api/groups');
    const g = d.data.groups || [];
    const gc = document.getElementById('groupContent');
    if (!gc) return;
    if (g.length === 0) {
      gc.innerHTML = '<div class="empty-state"><h3>暂无群组数据</h3></div>';
      return;
    }
    gc.innerHTML = `
      <div class="stats-grid" style="grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));">
        ${g.map(x => `
          <div class="stat-card purple">
            <div class="stat-icon">👥</div>
            <div class="stat-value" style="font-size: 24px;">${x.msg_count}</div>
            <div class="stat-label">${escHtml(x.title || x.chat_id)}</div>
            <div style="margin-top: 12px; display: flex; justify-content: space-between; font-size: 12px; color: #6b7280;">
              <span>入群 +${x.joined}</span>
              <span>离群 -${x.left}</span>
              <span style="color: ${x.net >= 0 ? '#10b981' : '#ef4444'}">净增 ${x.net >= 0 ? '+' : ''}${x.net}</span>
            </div>
          </div>
        `).join('')}
      </div>
    `;
  } catch (e) {
    console.error(e);
  }
}

async function loadConfig() {
  try {
    const d = await api('/api/config');
    const cfg = d.data.config || {};
    const cc = document.getElementById('configContent');
    if (!cc) return;
    const categories = {
      '核心互动': ['REPLY_CHANCE', 'REPLY_SPEED', 'REPLY_DELAY_MIN', 'REPLY_DELAY_MAX', 'MAX_MSG_LENGTH', 'RELAY_MODE_ENABLED', 'FAQ_TRACKING_ENABLED', 'FAQ_AUTO_REPLY_ENABLED'],
      '播报调度': ['GREETING_CONFIG', 'MYSTIC_BROADCAST_CONFIG', 'RELAY_MODE_ENABLED', 'WELCOME_MSG'],
      '安全治理': ['ENABLE_MESSAGE_DELETION', 'ORPHAN_CLEANUP_ENABLED', 'AD_CLEANUP_REACTIONS', 'RETROACTIVE_SCAN_ENABLED', 'EMOJI_MASK_DETECT', 'EDIT_DETECT_ENABLE', 'AD_DETECT_CONFIG', 'ANTIFLOOD_CONFIG', 'ANTI_DELETE_CONFIG', 'SPAM_LIMIT'],
      '业务配置': ['PROACTIVE_ENGAGE_CONFIG', 'CHECKIN_CONFIG', 'POINTS_RULES', 'POINTS_PER_INVITE', 'PRICE_LIST', 'REPLY_STICKER_CHANCE'],
      'AI模型': ['MODE_ROUTING', 'MODEL_POOLS', 'TEMPERATURE', 'MAX_TOKENS', 'TOP_P', 'FREQUENCY_PENALTY', 'PRESENCE_PENALTY', 'CURRENT_MODEL_INDEX'],
      '内容互动': ['SYSTEM_PROMPT', 'PROMPT_TEMPLATES', 'HATE_KEYWORDS', 'BANNED_WORDS', 'SLANG_DICT', 'PHOTO_KEYWORDS'],
      'Telegram接入': ['TELEGRAM_ALLOWED_UPDATES', 'TELEGRAM_BUSINESS_CONNECTION_ID'],
      '数据存储': ['LOG_LEVEL', 'LANGUAGE'],
    };
    const friendlyNames = {
      'REPLY_CHANCE': '群聊回复概率(%)', 'REPLY_DELAY_MIN': '回复延迟下限(秒)', 'REPLY_DELAY_MAX': '回复延迟上限(秒)',
      'REPLY_SPEED': '回复节奏', 'MAX_MSG_LENGTH': '最大回复长度', 'RELAY_MODE_ENABLED': '私聊中继',
      'FAQ_TRACKING_ENABLED': '问题历史留存', 'FAQ_AUTO_REPLY_ENABLED': 'FAQ模板自动回复',
      'GREETING_CONFIG': '问候配置', 'MYSTIC_BROADCAST_CONFIG': '传统文化播报配置', 'RELAY_MODE_ENABLED': '私聊中继', 'WELCOME_MSG': '入群欢迎',
      'ENABLE_MESSAGE_DELETION': '消息删除', 'ORPHAN_CLEANUP_ENABLED': '孤儿清理', 'AD_CLEANUP_REACTIONS': '广告反应清理', 'RETROACTIVE_SCAN_ENABLED': '启动追溯',
      'EMOJI_MASK_DETECT': 'Emoji面具检测', 'EDIT_DETECT_ENABLE': '编辑消息检测', 'AD_DETECT_CONFIG': '广告检测',
      'ANTIFLOOD_CONFIG': '反刷屏', 'ANTI_DELETE_CONFIG': '反撤回', 'SPAM_LIMIT': '刷屏限制',
      'PROACTIVE_ENGAGE_CONFIG': '主动搭讪', 'CHECKIN_CONFIG': '签到配置', 'POINTS_RULES': '积分规则',
      'POINTS_PER_INVITE': '邀请积分', 'PRICE_LIST': '价格表', 'REPLY_STICKER_CHANCE': '贴纸概率(%)',
      'MODE_ROUTING': '模式路由', 'MODEL_POOLS': '模型池', 'TEMPERATURE': '创意温度',
      'MAX_TOKENS': '最大Token数', 'TOP_P': 'Top-P采样',
      'FREQUENCY_PENALTY': '频率惩罚', 'PRESENCE_PENALTY': '存在惩罚',
      'CURRENT_MODEL_INDEX': '当前模型索引', 'SYSTEM_PROMPT': '系统人设',
      'PROMPT_TEMPLATES': '提示词模板', 'HATE_KEYWORDS': '反感关键词', 'BANNED_WORDS': '违禁词',
      'SLANG_DICT': '黑话词典', 'PHOTO_KEYWORDS': '内容关键词', 'LOG_LEVEL': '日志级别',
      'LANGUAGE': '语言', 'TELEGRAM_ALLOWED_UPDATES': '更新事件', 'TELEGRAM_BUSINESS_CONNECTION_ID': '业务连接ID',
    };
    let html = '';
    for (const [cat, keys] of Object.entries(categories)) {
      const items = keys.filter(k => k in cfg);
      if (items.length === 0) continue;
      html += `<h4 style="color:#60a5fa; margin:16px 0 8px; font-size:14px;">${escHtml(cat)}</h4>`;
      html += '<div style="display:grid; grid-template-columns:1fr 1fr; gap:8px;">';
      for (const k of items) {
        const v = cfg[k];
        const label = friendlyNames[k] || k;
        if (typeof v === 'boolean') {
          html += `<div style="display:flex; align-items:center; gap:8px; padding:8px 12px; background:#1e1e2e; border-radius:8px;">
            <label style="flex:1; color:#94a3b8; font-size:13px;">${escHtml(label)}</label>
            <input type="checkbox" ${v ? 'checked' : ''} onchange="quickSaveConfig('${escHtml(k)}', this.checked)" style="width:18px; height:18px;">
          </div>`;
        } else if (typeof v === 'number') {
          html += `<div style="display:flex; align-items:center; gap:8px; padding:8px 12px; background:#1e1e2e; border-radius:8px;">
            <label style="color:#94a3b8; font-size:13px; min-width:100px;">${escHtml(label)}</label>
            <input type="number" value="${v}" onchange="quickSaveConfig('${escHtml(k)}', parseFloat(this.value))" style="width:80px; padding:4px 8px; background:#0f0f1a; border:1px solid rgba(255,255,255,0.1); border-radius:6px; color:#e2e8f0; font-size:13px; text-align:right;">
          </div>`;
        } else if (typeof v === 'string') {
          const short = v.length > 30 ? v.substring(0, 30) + '...' : v;
          html += `<div style="display:flex; align-items:center; gap:8px; padding:8px 12px; background:#1e1e2e; border-radius:8px;">
            <label style="color:#94a3b8; font-size:13px; min-width:100px;">${escHtml(label)}</label>
            <input type="text" value="${escHtml(v)}" onchange="quickSaveConfig('${escHtml(k)}', this.value)" style="flex:1; padding:4px 8px; background:#0f0f1a; border:1px solid rgba(255,255,255,0.1); border-radius:6px; color:#e2e8f0; font-size:13px;">
          </div>`;
        } else if (Array.isArray(v)) {
          html += `<div style="display:flex; align-items:center; gap:8px; padding:8px 12px; background:#1e1e2e; border-radius:8px;">
            <label style="color:#94a3b8; font-size:13px; min-width:100px;">${escHtml(label)}</label>
            <input type="text" value="${escHtml(v.join(', '))}" onchange="quickSaveConfig('${escHtml(k)}', this.value.split(/[,，]/).map(s=>s.trim()).filter(s=>s))" style="flex:1; padding:4px 8px; background:#0f0f1a; border:1px solid rgba(255,255,255,0.1); border-radius:6px; color:#e2e8f0; font-size:13px;">
          </div>`;
        }
      }
      html += '</div>';
    }
    const uncategorized = Object.keys(cfg).filter(k => !Object.values(categories).flat().includes(k));
    if (uncategorized.length > 0) {
      html += `<h4 style="color:#60a5fa; margin:16px 0 8px; font-size:14px;">其他配置</h4>`;
      html += '<table class="data-table"><thead><tr><th>配置项</th><th>当前值</th><th>操作</th></tr></thead><tbody>';
      for (const k of uncategorized) {
        const v = cfg[k];
        html += `<tr><td style="font-weight:500;">${escHtml(k)}</td>
          <td style="max-width:300px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escHtml(typeof v === 'object' ? JSON.stringify(v) : String(v))}</td>
          <td><button class="btn btn-secondary" style="padding:6px 12px; font-size:12px;" onclick="editConfig(${JSON.stringify(k)}, ${JSON.stringify(typeof v === 'object' ? JSON.stringify(v) : String(v))})">编辑</button></td></tr>`;
      }
      html += '</tbody></table>';
    }
    cc.innerHTML = html || '<div class="empty-state"><h3>暂无配置数据</h3></div>';
  } catch (e) { console.error(e); }
}

async function quickSaveConfig(key, value) {
  try {
    const r = await api('/api/config/update', {
      method: 'POST',
      body: JSON.stringify({key, value})
    });
    showToast(r.ok ? `${key} 已更新（5到8秒内自动生效）` : (r.msg || '更新失败'), r.ok ? 'success' : 'error');
  } catch(e) { showToast('更新失败', 'error'); }
}

function editConfig(key, value) {
  const newValue = prompt(`修改配置项 "${key}":`, value);
  if (newValue === null) return;
  try {
    let parsedValue = newValue;
    try { parsedValue = JSON.parse(newValue); } catch {}
    api('/api/config/update', {
      method: 'POST',
      body: JSON.stringify({ key, value: parsedValue }),
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
    }).then(() => {
      showToast('配置已更新', 'success');
      loadConfig();
    }).catch(e => showToast('更新失败: ' + e.message, 'error'));
  } catch (e) {
    showToast('更新失败', 'error');
  }
}

function applyNlConfig() {
  const input = document.getElementById('nlConfigInput');
  if (!input) return;
  const text = input.value.trim();
  if (!text) return;
  api('/api/config/natural', {
    method: 'POST',
    body: JSON.stringify({ text }),
    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
  }).then((res) => {
    showToast(res.msg || '已处理', 'success');
    input.value = '';
    loadConfig();
  }).catch((e) => {
    showToast(e.message || '无法解析指令，请尝试更明确的描述', 'error');
  });
}

async function loadLogs(page = 1) {
  try {
    const d = await api(`/api/logs?page=${page}&per_page=30`);
    const logs = d.data.logs || [];
    const lc = document.getElementById('logsContent');
    if (!lc) return;
    if (logs.length === 0) {
      lc.innerHTML = '<div class="empty-state"><h3>暂无日志数据</h3></div>';
      return;
    }
    lc.innerHTML = `
      <table class="data-table">
        <thead>
          <tr>
            <th>时间</th><th>群ID</th><th>Bot消息ID</th><th>用户消息ID</th><th>已回复</th>
          </tr>
        </thead>
        <tbody>
          ${logs.map(l => `
            <tr>
              <td style="font-size: 12px; color: #6b7280;">${formatTime(l.ts)}</td>
              <td>${l.chat_id || '-'}</td>
              <td>${l.bot_msg_id || '-'}</td>
              <td>${l.user_msg_id || '-'}</td>
              <td>${l.replied ? '<span class="badge badge-success">✅</span>' : '<span class="badge badge-warning">⏳</span>'}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
      <div id="logsPagination" class="pagination"></div>
    `;
    renderPagination(d.data.pagination);
  } catch (e) {
    console.error(e);
  }
}

function searchLogs() {
  const keyword = document.getElementById('logSearchInput')?.value;
  if (!keyword) return;
  api(`/api/logs/search?keyword=${encodeURIComponent(keyword)}`).then(d => {
    const logs = d.data.logs || [];
    const lc = document.getElementById('logsContent');
    if (!lc) return;
    if (logs.length === 0) {
      lc.innerHTML = '<div class="empty-state"><h3>未找到匹配的日志</h3></div>';
      return;
    }
    lc.innerHTML = `
      <table class="data-table">
        <thead>
          <tr>
            <th>时间</th><th>群ID</th><th>Bot消息ID</th><th>用户消息ID</th><th>已回复</th>
          </tr>
        </thead>
        <tbody>
          ${logs.map(l => `
            <tr>
              <td style="font-size: 12px; color: #6b7280;">${formatTime(l.ts)}</td>
              <td>${l.chat_id || '-'}</td>
              <td>${l.bot_msg_id || '-'}</td>
              <td>${l.user_msg_id || '-'}</td>
              <td>${l.replied ? '<span class="badge badge-success">✅</span>' : '<span class="badge badge-warning">⏳</span>'}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  }).catch(e => showToast('搜索失败', 'error'));
}

function downloadReport() {
  fetch(API_BASE + '/api/report/download', {credentials: 'same-origin'})
    .then(r => {
      if (!r.ok) throw new Error('下载失败');
      return r.blob();
    })
    .then(blob => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = 'mory_report.csv';
      document.body.appendChild(a); a.click();
      document.body.removeChild(a); URL.revokeObjectURL(url);
    })
    .catch(e => showToast('下载失败: ' + e.message, 'error'));
}

// ============ 功能配置页面函数 ============

// 通用toggle开关HTML
function toggleHtml(id, checked, label) {
  return `<div style="display:flex; align-items:center; gap:12px; margin-bottom:12px;">
    <label style="position:relative; display:inline-block; width:48px; height:26px; cursor:pointer;">
      <input type="checkbox" id="${id}" ${checked ? 'checked' : ''} style="opacity:0; width:0; height:0;"
        onchange="this.parentElement.querySelector('span').style.background=this.checked?'#3b82f6':'#4a4a6a'; this.parentElement.querySelector('span::before')">
      <span style="position:absolute; top:0; left:0; right:0; bottom:0; background:${checked?'#3b82f6':'#4a4a6a'}; border-radius:13px; transition:0.3s;">
        <span style="position:absolute; content:''; height:20px; width:20px; left:${checked?'26px':'3px'}; bottom:3px; background:white; border-radius:50%; transition:0.3s;"></span>
      </span>
    </label>
    <span style="color:#94a3b8; font-size:14px;">${label}</span>
  </div>`;
}

// ---- 验证码配置 ----
async function loadVerification() {
  try {
    const d = await api('/api/settings/verification');
    const vc = d.data;
    const el = document.getElementById('verificationContent');
    if (!el) return;
    el.innerHTML = `
      <div class="card" style="margin-bottom:20px;">
        <h3 style="color:#fff; margin-bottom:16px;">验证码设置</h3>
        <div style="margin-bottom:16px;">
          <label style="display:flex; align-items:center; gap:8px; color:#94a3b8; font-size:13px; margin-bottom:8px; cursor:pointer;">
            <input type="checkbox" id="vcEnable" ${vc.enable ? 'checked' : ''} style="width:18px; height:18px;">
            启用入群验证码
          </label>
        </div>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:16px;">
          <div>
            <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">验证模式</label>
            <select id="vcMode" style="width:100%; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px;">
              <option value="button" ${vc.mode==='button'?'selected':''}>按钮验证</option>
              <option value="math" ${vc.mode==='math'?'selected':''}>数学验证</option>
              <option value="text" ${vc.mode==='text'?'selected':''}>文字验证</option>
            </select>
          </div>
          <div>
            <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">超时时间(秒)</label>
            <input id="vcTimeout" type="number" value="${vc.timeout||120}" min="10" max="300" style="width:100%; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px;">
          </div>
        </div>
        <div style="margin-bottom:16px;">
          <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">最大尝试次数</label>
          <input id="vcMaxAttempts" type="number" value="${vc.max_attempts||3}" min="1" max="10" style="width:200px; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px;">
        </div>
        <button class="btn btn-primary" onclick="saveVerification()">保存配置</button>
      </div>
      <div class="card">
        <h3 style="color:#fff; margin-bottom:12px;">模式说明</h3>
        <table class="data-table">
          <thead><tr><th>模式</th><th>说明</th></tr></thead>
          <tbody>
            <tr><td style="font-weight:500;">button</td><td>点击按钮即可通过验证，最简单</td></tr>
            <tr><td style="font-weight:500;">math</td><td>需要回答简单数学题，如"3+5=?"</td></tr>
            <tr><td style="font-weight:500;">text</td><td>需要输入指定文字，如"输入 我不是机器人"</td></tr>
          </tbody>
        </table>
      </div>
    `;
  } catch(e) { console.error(e); }
}

async function saveVerification() {
  const data = {
    enable: document.getElementById('vcEnable').checked,
    mode: document.getElementById('vcMode').value,
    timeout: parseInt(document.getElementById('vcTimeout').value) || 120,
    max_attempts: parseInt(document.getElementById('vcMaxAttempts').value) || 3
  };
  try {
    const r = await api('/api/settings/verification', { method: 'POST', body: JSON.stringify(data) });
    showToast(r.msg || '保存成功', 'success');
  } catch(e) { showToast('保存失败', 'error'); }
}

// ---- 欢迎定制 ----
async function loadWelcomeConfig() {
  try {
    const d = await api('/api/settings/welcome');
    const wc = d.data;
    const el = document.getElementById('welcomeContent');
    if (!el) return;
    el.innerHTML = `
      <div class="card" style="margin-bottom:20px;">
        <h3 style="color:#fff; margin-bottom:16px;">欢迎/告别/群规</h3>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:16px;">
          <label style="display:flex; align-items:center; gap:8px; color:#94a3b8; font-size:13px; cursor:pointer;">
            <input type="checkbox" id="wcEnableWelcome" ${wc.enable_welcome?'checked':''} style="width:18px; height:18px;">
            启用入群欢迎
          </label>
          <label style="display:flex; align-items:center; gap:8px; color:#94a3b8; font-size:13px; cursor:pointer;">
            <input type="checkbox" id="wcEnableGoodbye" ${wc.enable_goodbye?'checked':''} style="width:18px; height:18px;">
            启用离群告别
          </label>
          <label style="display:flex; align-items:center; gap:8px; color:#94a3b8; font-size:13px; cursor:pointer;">
            <input type="checkbox" id="wcEnableRules" ${wc.enable_rules?'checked':''} style="width:18px; height:18px;">
            启用群规推送
          </label>
          <label style="display:flex; align-items:center; gap:8px; color:#94a3b8; font-size:13px; cursor:pointer;">
            <input type="checkbox" id="wcCleanWelcome" ${wc.clean_welcome?'checked':''} style="width:18px; height:18px;">
            自动清理欢迎消息
          </label>
        </div>
        <div style="margin-bottom:16px;">
          <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">欢迎语内容</label>
          <textarea id="wcWelcomeText" style="width:100%; min-height:80px; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px; resize:vertical;">${escHtml(wc.welcome_text||'')}</textarea>
          <p style="color:#6b7280; font-size:12px; margin-top:4px;">支持变量: {user} {mention} {first_name} {id} {chat_id}</p>
        </div>
        <div style="margin-bottom:16px;">
          <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">告别语内容</label>
          <textarea id="wcGoodbyeText" style="width:100%; min-height:60px; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px; resize:vertical;">${escHtml(wc.goodbye_text||'')}</textarea>
        </div>
        <div style="margin-bottom:16px;">
          <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">群规内容</label>
          <textarea id="wcRulesText" style="width:100%; min-height:80px; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px; resize:vertical;">${escHtml(wc.rules_text||'')}</textarea>
        </div>
        <button class="btn btn-primary" onclick="saveWelcomeConfig()">保存配置</button>
      </div>
      <div class="card">
        <h3 style="color:#fff; margin-bottom:12px;">变量说明</h3>
        <table class="data-table">
          <thead><tr><th>变量</th><th>说明</th><th>示例</th></tr></thead>
          <tbody>
            <tr><td style="font-weight:500; color:#60a5fa;">{user}</td><td>用户全名</td><td>张三</td></tr>
            <tr><td style="font-weight:500; color:#60a5fa;">{mention}</td><td>@用户名链接</td><td>@zhangsan</td></tr>
            <tr><td style="font-weight:500; color:#60a5fa;">{first_name}</td><td>用户名</td><td>张</td></tr>
            <tr><td style="font-weight:500; color:#60a5fa;">{id}</td><td>用户ID</td><td>123456789</td></tr>
            <tr><td style="font-weight:500; color:#60a5fa;">{chat_id}</td><td>群组ID</td><td>-100123456</td></tr>
          </tbody>
        </table>
      </div>
    `;
  } catch(e) { console.error(e); }
}

async function saveWelcomeConfig() {
  const data = {
    welcome_text: document.getElementById('wcWelcomeText').value,
    goodbye_text: document.getElementById('wcGoodbyeText').value,
    rules_text: document.getElementById('wcRulesText').value,
    enable_welcome: document.getElementById('wcEnableWelcome').checked,
    enable_goodbye: document.getElementById('wcEnableGoodbye').checked,
    enable_rules: document.getElementById('wcEnableRules').checked,
    clean_welcome: document.getElementById('wcCleanWelcome').checked
  };
  try {
    const r = await api('/api/settings/welcome', { method: 'POST', body: JSON.stringify(data) });
    showToast(r.msg || '保存成功', 'success');
  } catch(e) { showToast('保存失败', 'error'); }
}

// ---- 夜间模式 ----
async function loadNightMode() {
  try {
    const d = await api('/api/settings/nightmode');
    const nc = d.data;
    const el = document.getElementById('nightmodeContent');
    if (!el) return;
    let hourOptions = '';
    for (let h = 0; h <= 23; h++) hourOptions += `<option value="${h}">${String(h).padStart(2,'0')}:00</option>`;
    el.innerHTML = `
      <div class="card" style="margin-bottom:20px;">
        <h3 style="color:#fff; margin-bottom:16px;">夜间模式设置</h3>
        <div style="margin-bottom:16px;">
          <label style="display:flex; align-items:center; gap:8px; color:#94a3b8; font-size:13px; cursor:pointer;">
            <input type="checkbox" id="nmEnable" ${nc.enable?'checked':''} style="width:18px; height:18px;">
            启用夜间静默模式
          </label>
          <p style="color:#6b7280; font-size:12px; margin-top:4px;">开启后，在设定时段内Bot将减少主动发言</p>
        </div>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:16px;">
          <div>
            <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">开始时间</label>
            <select id="nmStartHour" style="width:100%; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px;">
              ${hourOptions}
            </select>
          </div>
          <div>
            <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">结束时间</label>
            <select id="nmEndHour" style="width:100%; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px;">
              ${hourOptions}
            </select>
          </div>
        </div>
        <button class="btn btn-primary" onclick="saveNightMode()">保存配置</button>
      </div>
      <div class="card">
        <h3 style="color:#fff; margin-bottom:12px;">时段说明</h3>
        <p style="color:#94a3b8; font-size:14px;">当前配置: 每日 <span style="color:#60a5fa; font-weight:600;">${String(nc.start_hour).padStart(2,'0')}:00</span> 至 <span style="color:#60a5fa; font-weight:600;">${String(nc.end_hour).padStart(2,'0')}:00</span> 为夜间静默时段${nc.enable ? '（已启用）' : '（未启用）'}</p>
        <p style="color:#6b7280; font-size:13px; margin-top:8px;">支持跨午夜设置，如 23:00 至 07:00 表示晚11点到次日早7点</p>
      </div>
    `;
    document.getElementById('nmStartHour').value = nc.start_hour;
    document.getElementById('nmEndHour').value = nc.end_hour;
  } catch(e) { console.error(e); }
}

async function saveNightMode() {
  const data = {
    enable: document.getElementById('nmEnable').checked,
    start_hour: parseInt(document.getElementById('nmStartHour').value),
    end_hour: parseInt(document.getElementById('nmEndHour').value)
  };
  try {
    const r = await api('/api/settings/nightmode', { method: 'POST', body: JSON.stringify(data) });
    showToast(r.msg || '保存成功', 'success');
    loadNightMode();
  } catch(e) { showToast('保存失败', 'error'); }
}

// ---- 定点播报 ----
async function loadBroadcasts() {
  try {
    const d = await api('/api/settings/broadcasts');
    const broadcasts = d.data.broadcasts || [];
    const el = document.getElementById('broadcastsContent');
    if (!el) return;
    el.innerHTML = `
      <div class="card" style="margin-bottom:20px;">
        <h3 style="color:#fff; margin-bottom:16px;">新增播报项</h3>
        <div style="display:grid; grid-template-columns:1fr 1fr 1fr 2fr auto; gap:12px; align-items:end;">
          <div>
            <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">ID</label>
            <input id="bcId" type="text" placeholder="唯一标识" style="width:100%; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px;">
          </div>
          <div>
            <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">时间</label>
            <div style="display:flex; gap:4px;">
              <input id="bcHour" type="number" value="8" min="0" max="23" style="width:50%; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px;">
              <input id="bcMinute" type="number" value="0" min="0" max="59" style="width:50%; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px;">
            </div>
          </div>
          <div>
            <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">类型</label>
            <select id="bcType" style="width:100%; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px;">
              <option value="text">文本</option>
            </select>
          </div>
          <div>
            <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">播报内容</label>
            <input id="bcContent" type="text" placeholder="播报内容" style="width:100%; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px;">
          </div>
          <button class="btn btn-primary" onclick="addBroadcast()">添加</button>
        </div>
      </div>
      <div class="card">
        <h3 style="color:#fff; margin-bottom:16px;">播报列表 <span style="color:#6b7280; font-size:14px;">(${broadcasts.length}项)</span></h3>
        ${broadcasts.length === 0 ? '<p style="color:#6b7280;">暂无播报项</p>' : `
        <table class="data-table">
          <thead><tr><th>ID</th><th>时间</th><th>内容</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>
            ${broadcasts.map(b => `
              <tr>
                <td style="font-weight:500;">${escHtml(b.id)}</td>
                <td>${String(b.hour||0).padStart(2,'0')}:${String(b.minute||0).padStart(2,'0')}</td>
                <td style="max-width:300px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escHtml(b.content)}</td>
                <td>${b.enabled ? '<span class="badge badge-success">启用</span>' : '<span class="badge badge-warning">禁用</span>'}</td>
                <td><button class="btn btn-secondary" style="padding:6px 12px; font-size:12px;" onclick="deleteBroadcast('${escHtml(b.id)}')">删除</button></td>
              </tr>
            `).join('')}
          </tbody>
        </table>`}
      </div>
    `;
  } catch(e) { console.error(e); }
}

async function addBroadcast() {
  const bid = document.getElementById('bcId').value.trim();
  if (!bid) { showToast('请输入播报ID', 'error'); return; }
  const data = {
    id: bid,
    hour: parseInt(document.getElementById('bcHour').value) || 0,
    minute: parseInt(document.getElementById('bcMinute').value) || 0,
    content: document.getElementById('bcContent').value.trim(),
    type: document.getElementById('bcType').value,
    enabled: true
  };
  if (!data.content) { showToast('请输入播报内容', 'error'); return; }
  try {
    const r = await api('/api/settings/broadcasts', { method: 'POST', body: JSON.stringify(data) });
    showToast(r.msg || '添加成功', 'success');
    loadBroadcasts();
  } catch(e) { showToast('添加失败', 'error'); }
}

async function deleteBroadcast(bid) {
  if (!confirm('确定删除播报项 "' + bid + '" 吗？')) return;
  try {
    const r = await api('/api/settings/broadcasts', { method: 'DELETE', body: JSON.stringify({id: bid}) });
    showToast(r.msg || '删除成功', 'success');
    loadBroadcasts();
  } catch(e) { showToast('删除失败', 'error'); }
}

// ---- 联邦封禁 ----
async function loadFederation() {
  try {
    const d = await api('/api/settings/federation');
    const bans = d.data.bans || [];
    const el = document.getElementById('federationContent');
    if (!el) return;
    el.innerHTML = `
      <div class="card" style="margin-bottom:20px;">
        <h3 style="color:#fff; margin-bottom:16px;">新增联邦封禁</h3>
        <div style="display:flex; gap:12px; align-items:end;">
          <div style="flex:1;">
            <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">用户ID</label>
            <input id="fedUserId" type="number" placeholder="Telegram用户ID" style="width:100%; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px;">
          </div>
          <div style="flex:2;">
            <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">封禁原因</label>
            <input id="fedReason" type="text" placeholder="封禁原因" style="width:100%; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px;">
          </div>
          <button class="btn btn-primary" onclick="addFederationBan()">封禁</button>
        </div>
      </div>
      <div class="card">
        <h3 style="color:#fff; margin-bottom:16px;">封禁列表 <span style="color:#6b7280; font-size:14px;">(${bans.length}人)</span></h3>
        ${bans.length === 0 ? '<p style="color:#6b7280;">暂无联邦封禁记录</p>' : `
        <table class="data-table">
          <thead><tr><th>用户ID</th><th>原因</th><th>封禁者</th><th>时间</th><th>操作</th></tr></thead>
          <tbody>
            ${bans.map(b => `
              <tr>
                <td style="font-weight:500; font-family:'JetBrains Mono',monospace;">${b.user_id}</td>
                <td>${escHtml(b.reason||'-')}</td>
                <td>${b.banned_by || '系统'}</td>
                <td style="color:#6b7280;">${b.ts ? new Date(b.ts*1000).toLocaleString('zh-CN') : '-'}</td>
                <td><button class="btn btn-secondary" style="padding:6px 12px; font-size:12px;" onclick="removeFederationBan(${b.user_id})">解除</button></td>
              </tr>
            `).join('')}
          </tbody>
        </table>`}
      </div>
    `;
  } catch(e) { console.error(e); }
}

async function addFederationBan() {
  const userId = document.getElementById('fedUserId').value.trim();
  const reason = document.getElementById('fedReason').value.trim();
  if (!userId) { showToast('请输入用户ID', 'error'); return; }
  try {
    const r = await api('/api/settings/federation', { method: 'POST', body: JSON.stringify({user_id: parseInt(userId), reason: reason}) });
    showToast(r.msg || '封禁成功', 'success');
    loadFederation();
  } catch(e) { showToast('封禁失败', 'error'); }
}

async function removeFederationBan(userId) {
  if (!confirm('确定解除用户 ' + userId + ' 的联邦封禁吗？')) return;
  try {
    const r = await api('/api/settings/federation', { method: 'DELETE', body: JSON.stringify({user_id: userId}) });
    showToast(r.msg || '解除成功', 'success');
    loadFederation();
  } catch(e) { showToast('解除失败', 'error'); }
}

// ---- v5.18.0 播报格式 / 按钮样式 / Custom Emoji / 用户画像 / A/B测试 / 按钮统计 ----

async function loadBroadcastFormat() {
  try {
    const d = await api('/api/config/broadcast-format');
    const data = d.data || {};
    const el = document.getElementById('broadcastFormatContent');
    if (!el) return;
    el.innerHTML = `
      <div class="card" style="margin-bottom:20px;">
        <h3 style="color:#fff; margin-bottom:16px;">📝 播报格式开关</h3>
        <div style="margin-bottom:16px;">
          <label style="display:flex; align-items:center; gap:8px; color:#94a3b8; font-size:13px; cursor:pointer;">
            <input type="checkbox" id="richMsgEnabled" ${data.rich_message_enabled ? 'checked' : ''} style="width:18px;height:18px;cursor:pointer;">
            <span>启用 Rich Messages（Bot API 10.1+） - 失败时自动回退 HTML</span>
          </label>
        </div>
        <div style="margin-bottom:16px;">
          <label style="display:flex; align-items:center; gap:8px; color:#94a3b8; font-size:13px; cursor:pointer;">
            <input type="checkbox" id="imgCardEnabled" ${data.broadcast_image_card_enabled ? 'checked' : ''} style="width:18px;height:18px;cursor:pointer;">
            <span>全局启用图片卡（各播报类型仍需单独开启才会实际生图）</span>
          </label>
        </div>
        <div style="margin-bottom:16px;">
          <label style="display:flex; align-items:center; gap:8px; color:#94a3b8; font-size:13px; cursor:pointer;">
            <input type="checkbox" id="themeEnabled" ${data.broadcast_theme_enabled !== false ? 'checked' : ''} style="width:18px;height:18px;cursor:pointer;">
            <span>启用主题引擎（根据时段/内容自动匹配配色）</span>
          </label>
        </div>
        <div style="margin-bottom:16px;">
          <label style="display:flex; align-items:center; gap:8px; color:#94a3b8; font-size:13px; cursor:pointer;">
            <input type="checkbox" id="templateVariationEnabled" ${data.broadcast_template_variation_enabled ? 'checked' : ''} style="width:18px;height:18px;cursor:pointer;">
            <span>启用模板轻变化（已清空变体库，开启无实际效果）</span>
          </label>
        </div>
        <div style="margin-bottom:16px;">
          <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">格式版本</label>
          <select id="bcFmtVersion" style="width:100%; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px;">
            <option value="html" ${data.broadcast_format_version==='html'?'selected':''}>HTML（当前默认）</option>
            <option value="rich" ${data.broadcast_format_version==='rich'?'selected':''}>Rich Message（原生组件）</option>
            <option value="auto" ${data.broadcast_format_version==='auto'?'selected':''}>Auto（智能选择）</option>
          </select>
        </div>
        <div style="margin-bottom:16px;">
          <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">排版样式</label>
          <div style="display:flex; flex-wrap:wrap; gap:12px;">
            <label style="display:flex; align-items:center; gap:6px; color:#94a3b8; font-size:13px;">
              <input type="checkbox" id="styTitle" ${(data.rich_message_style||{}).title_bold?'checked':''}> 标题加粗
            </label>
            <label style="display:flex; align-items:center; gap:6px; color:#94a3b8; font-size:13px;">
              <input type="checkbox" id="styBadge" ${(data.rich_message_style||{}).badge_italic?'checked':''}> 角标斜体
            </label>
            <label style="display:flex; align-items:center; gap:6px; color:#94a3b8; font-size:13px;">
              <input type="checkbox" id="styFooter" ${(data.rich_message_style||{}).footer_expandable?'checked':''}> 补充可折叠
            </label>
            <label style="display:flex; align-items:center; gap:6px; color:#94a3b8; font-size:13px;">
              <input type="checkbox" id="styEmoji" ${(data.rich_message_style||{}).emoji_custom?'checked':''}> Custom Emoji
            </label>
          </div>
        </div>
        <button class="btn btn-primary" onclick="saveBroadcastFormat()">保存（5-8秒内生效）</button>
      </div>
      <div class="card">
        <h3 style="color:#fff; margin-bottom:12px;">📊 当前生效状态</h3>
        <p style="color:#94a3b8; font-size:13px;">Rich Message: <span style="color:${data.rich_message_enabled?'#10b981':'#6b7280'};">${data.rich_message_enabled?'启用':'关闭'}</span></p>
        <p style="color:#94a3b8; font-size:13px;">格式版本: <span style="color:#60a5fa;">${data.broadcast_format_version}</span></p>
        <p style="color:#94a3b8; font-size:13px;">全局图片卡: <span style="color:${data.broadcast_image_card_enabled?'#10b981':'#6b7280'};">${data.broadcast_image_card_enabled?'启用':'关闭'}</span></p>
        <p style="color:#94a3b8; font-size:13px;">主题引擎: <span style="color:${data.broadcast_theme_enabled!==false?'#10b981':'#6b7280'};">${data.broadcast_theme_enabled!==false?'启用':'关闭'}</span></p>
        <p style="color:#94a3b8; font-size:13px;">模板轻变化: <span style="color:${data.broadcast_template_variation_enabled?'#10b981':'#6b7280'};">${data.broadcast_template_variation_enabled?'启用':'关闭'}</span></p>
        <p style="color:#94a3b8; font-size:13px;">说明：关闭 Rich Message 时所有播报使用 HTML 卡片；开启时优先尝试 Rich Message，失败自动回退 HTML。图片卡需全局开关与类型开关同时开启。</p>
      </div>
    `;
  } catch(e) { showToast('加载失败', 'error'); }
}

async function saveBroadcastFormat() {
  try {
    const body = {
      rich_message_enabled: document.getElementById('richMsgEnabled').checked,
      broadcast_format_version: document.getElementById('bcFmtVersion').value,
      broadcast_image_card_enabled: document.getElementById('imgCardEnabled').checked,
      broadcast_theme_enabled: document.getElementById('themeEnabled').checked,
      broadcast_template_variation_enabled: document.getElementById('templateVariationEnabled').checked,
      rich_message_style: {
        title_bold: document.getElementById('styTitle').checked,
        badge_italic: document.getElementById('styBadge').checked,
        footer_expandable: document.getElementById('styFooter').checked,
        emoji_custom: document.getElementById('styEmoji').checked,
      }
    };
    const r = await api('/api/config/broadcast-format', { method: 'POST', body: JSON.stringify(body) });
    showToast(r.msg || '已保存', 'success');
    loadBroadcastFormat();
  } catch(e) { showToast('保存失败', 'error'); }
}

async function loadButtonStyle() {
  try {
    const d = await api('/api/config/button-style');
    const data = d.data || {};
    const cmap = data.button_color_map || {};
    const el = document.getElementById('buttonStyleContent');
    if (!el) return;
    el.innerHTML = `
      <div class="card" style="margin-bottom:20px;">
        <h3 style="color:#fff; margin-bottom:16px;">🎨 彩色按钮开关</h3>
        <div style="margin-bottom:16px;">
          <label style="display:flex; align-items:center; gap:8px; color:#94a3b8; font-size:13px; cursor:pointer;">
            <input type="checkbox" id="btnStyleEnabled" ${data.button_style_enabled ? 'checked' : ''} style="width:18px;height:18px;cursor:pointer;">
            <span>启用彩色按钮（Bot API 9.4+） - 失败时自动回退默认样式</span>
          </label>
        </div>
        <h4 style="color:#e2e8f0; margin:16px 0 12px;">颜色映射（按钮ID → 样式）</h4>
        <div style="display:grid; grid-template-columns:repeat(2,1fr); gap:12px;">
          ${['buy','cancel','info','settings'].map(k => `
            <div>
              <label style="color:#94a3b8; font-size:12px; display:block; margin-bottom:4px;">${k}</label>
              <select id="cmap_${k}" style="width:100%; padding:8px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:6px; color:#e2e8f0; font-size:13px;">
                ${['default','primary','success','danger'].map(s => `<option value="${s}" ${cmap[k]===s?'selected':''}>${s}</option>`).join('')}
              </select>
            </div>
          `).join('')}
        </div>
        <button class="btn btn-primary" style="margin-top:16px;" onclick="saveButtonStyle()">保存（5-8秒内生效）</button>
      </div>
      <div class="card">
        <h3 style="color:#fff; margin-bottom:12px;">📊 预览</h3>
        <div style="display:flex; flex-wrap:wrap; gap:8px;">
          <span style="padding:8px 16px; background:#2481cc; border-radius:8px; color:#fff; font-size:13px;">default</span>
          <span style="padding:8px 16px; background:#5e9eff; border-radius:8px; color:#fff; font-size:13px;">primary</span>
          <span style="padding:8px 16px; background:#4dcb5d; border-radius:8px; color:#fff; font-size:13px;">success</span>
          <span style="padding:8px 16px; background:#e53935; border-radius:8px; color:#fff; font-size:13px;">danger</span>
        </div>
        <p style="color:#94a3b8; font-size:12px; margin-top:12px;">说明：样式仅在支持 Bot API 9.4+ 的客户端显示；旧客户端显示为默认颜色。</p>
      </div>
    `;
  } catch(e) { showToast('加载失败', 'error'); }
}

async function saveButtonStyle() {
  try {
    const cmap = {};
    ['buy','cancel','info','settings'].forEach(k => { cmap[k] = document.getElementById('cmap_'+k).value; });
    const r = await api('/api/config/button-style', { method: 'POST', body: JSON.stringify({ button_style_enabled: document.getElementById('btnStyleEnabled').checked, button_color_map: cmap }) });
    showToast(r.msg || '已保存', 'success');
    loadButtonStyle();
  } catch(e) { showToast('保存失败', 'error'); }
}

async function loadCustomEmojiPool() {
  try {
    const d = await api('/api/config/custom-emoji');
    const data = d.data || {};
    const pool = data.custom_emoji_pool || {};
    const el = document.getElementById('customEmojiContent');
    if (!el) return;
    el.innerHTML = `
      <div class="card" style="margin-bottom:20px;">
        <h3 style="color:#fff; margin-bottom:16px;">😀 Custom Emoji 池配置</h3>
        <div style="margin-bottom:16px;">
          <label style="display:flex; align-items:center; gap:8px; color:#94a3b8; font-size:13px; cursor:pointer;">
            <input type="checkbox" id="ceEnabled" ${data.custom_emoji_enabled ? 'checked' : ''} style="width:18px;height:18px;cursor:pointer;">
            <span>启用 Custom Emoji（需 Bot 有 Custom Emoji 权限）</span>
          </label>
        </div>
        <h4 style="color:#e2e8f0; margin:16px 0 12px;">Emoji 池（按钮ID → Emoji ID）</h4>
        <p style="color:#94a3b8; font-size:12px; margin-bottom:8px;">一行一个：按钮ID,emoji_id  例如：buy,5368324170671202286</p>
        <textarea id="cePool" rows="8" style="width:100%; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-family:monospace; font-size:13px;">${Object.entries(pool).map(([k,v])=>k+','+v).join('\\n')}</textarea>
        <button class="btn btn-primary" style="margin-top:16px;" onclick="saveCustomEmojiPool()">保存（5-8秒内生效）</button>
      </div>
    `;
  } catch(e) { showToast('加载失败', 'error'); }
}

async function saveCustomEmojiPool() {
  try {
    const pool = {};
    const lines = document.getElementById('cePool').value.split('\\n');
    lines.forEach(line => {
      const [k, v] = line.split(',').map(s => s.trim());
      if (k && v) pool[k] = v;
    });
    const r = await api('/api/config/custom-emoji', { method: 'POST', body: JSON.stringify({ custom_emoji_enabled: document.getElementById('ceEnabled').checked, custom_emoji_pool: pool }) });
    showToast(r.msg || '已保存', 'success');
    loadCustomEmojiPool();
  } catch(e) { showToast('保存失败', 'error'); }
}

async function loadUserProfile() {
  try {
    const d = await api('/api/config/user-profile');
    const data = d.data || {};
    const el = document.getElementById('userProfileContent');
    if (!el) return;
    el.innerHTML = `
      <div class="card" style="margin-bottom:20px;">
        <h3 style="color:#fff; margin-bottom:16px;">👤 用户画像个性化</h3>
        <div style="margin-bottom:16px;">
          <label style="display:flex; align-items:center; gap:8px; color:#94a3b8; font-size:13px; cursor:pointer;">
            <input type="checkbox" id="upEnabled" ${data.user_profile_enabled ? 'checked' : ''} style="width:18px;height:18px;cursor:pointer;">
            <span>启用用户画像个性化播报</span>
          </label>
        </div>
        <h4 style="color:#e2e8f0; margin:16px 0 12px;">个性化规则</h4>
        <div style="color:#94a3b8; font-size:13px; line-height:1.8;">
          <p>🟢 <b style="color:#fff;">VIP 用户</b>（level ≥ 5 或 tags 包含 vip）：专属 emoji ✨ + 尊贵称呼</p>
          <p>🟢 <b style="color:#fff;">高等级用户</b>（level ≥ 3）：感谢话术 💝 感谢您的陪伴与支持</p>
          <p>🟢 <b style="color:#fff;">高价值用户</b>（high_value 标签）：标题追加"精选推荐"</p>
          <p>🟢 <b style="color:#fff;">兴趣匹配</b>：tarot → 🔮（晚/夜时段）；treehole → 🌳</p>
        </div>
        <button class="btn btn-primary" style="margin-top:16px;" onclick="saveUserProfile()">保存（5-8秒内生效）</button>
      </div>
      <div class="card">
        <h3 style="color:#fff; margin-bottom:12px;">📊 当前状态</h3>
        <p style="color:#94a3b8; font-size:13px;">画像个性化: <span style="color:${data.user_profile_enabled?'#10b981':'#6b7280'};">${data.user_profile_enabled?'启用':'关闭'}</span></p>
        <p style="color:#94a3b8; font-size:13px;">数据来源: <span style="color:#60a5fa;">user_profiles 表（自动学习 + 手动配置）</span></p>
      </div>
    `;
  } catch(e) { showToast('加载失败', 'error'); }
}

async function saveUserProfile() {
  try {
    const r = await api('/api/config/user-profile', { method: 'POST', body: JSON.stringify({ user_profile_enabled: document.getElementById('upEnabled').checked }) });
    showToast(r.msg || '已保存', 'success');
    loadUserProfile();
  } catch(e) { showToast('保存失败', 'error'); }
}

async function loadABTest() {
  try {
    const d = await api('/api/ab-test/stats');
    const data = d.data || {};
    const el = document.getElementById('abTestContent');
    if (!el) return;
    const htmlCtr = (data.html_conversions || 0) / Math.max(1, data.html_sent || 1) * 100;
    const richCtr = (data.rich_conversions || 0) / Math.max(1, data.rich_sent || 1) * 100;
    el.innerHTML = `
      <div class="card" style="margin-bottom:20px;">
        <h3 style="color:#fff; margin-bottom:16px;">🧪 A/B 测试统计</h3>
        <div style="display:grid; grid-template-columns:repeat(2,1fr); gap:16px;">
          <div style="background:rgba(96,165,250,0.1); border:1px solid rgba(96,165,250,0.3); border-radius:12px; padding:16px;">
            <h4 style="color:#60a5fa; margin:0 0 8px;">HTML 卡片（对照组）</h4>
            <p style="color:#94a3b8; font-size:13px; margin:4px 0;">已发送: <span style="color:#fff; font-family:monospace;">${data.html_sent || 0}</span></p>
            <p style="color:#94a3b8; font-size:13px; margin:4px 0;">已转化: <span style="color:#fff; font-family:monospace;">${data.html_conversions || 0}</span></p>
            <p style="color:#94a3b8; font-size:13px; margin:4px 0;">转化率: <span style="color:#10b981; font-family:monospace; font-size:18px;">${htmlCtr.toFixed(2)}%</span></p>
          </div>
          <div style="background:rgba(167,139,250,0.1); border:1px solid rgba(167,139,250,0.3); border-radius:12px; padding:16px;">
            <h4 style="color:#a78bfa; margin:0 0 8px;">Rich Message（实验组）</h4>
            <p style="color:#94a3b8; font-size:13px; margin:4px 0;">已发送: <span style="color:#fff; font-family:monospace;">${data.rich_sent || 0}</span></p>
            <p style="color:#94a3b8; font-size:13px; margin:4px 0;">已转化: <span style="color:#fff; font-family:monospace;">${data.rich_conversions || 0}</span></p>
            <p style="color:#94a3b8; font-size:13px; margin:4px 0;">转化率: <span style="color:#10b981; font-family:monospace; font-size:18px;">${richCtr.toFixed(2)}%</span></p>
          </div>
        </div>
        <p style="color:#94a3b8; font-size:12px; margin-top:16px;">说明：A/B 测试默认关闭（AB_TEST_ENABLED=false）。开启后将随机分配用户到两组，追踪 7 天转化率差异。</p>
        <button class="btn btn-secondary" style="margin-top:12px;" onclick="showToast('A/B 测试配置请通过 /api/config/broadcast-format 切换格式版本', 'info')">配置开关</button>
      </div>
    `;
  } catch(e) { showToast('加载失败：' + (e.message || e), 'error'); document.getElementById('abTestContent').innerHTML = '<p style="color:#6b7280;">暂无 A/B 测试数据</p>'; }
}

async function loadButtonStats() {
  try {
    const d = await api('/api/button-stats/stats');
    const data = d.data || {};
    const el = document.getElementById('buttonStatsContent');
    if (!el) return;
    const stats = data.stats || [];
    el.innerHTML = `
      <div class="card" style="margin-bottom:20px;">
        <h3 style="color:#fff; margin-bottom:16px;">📊 按钮点击统计</h3>
        ${stats.length === 0 ? '<p style="color:#6b7280;">暂无按钮点击数据（按钮点击追踪已默认开启，但需要 bot 收到按钮回调后才会记录）</p>' : `
          <table class="data-table">
            <thead><tr><th>按钮ID</th><th>样式</th><th>展示次数</th><th>点击次数</th><th>点击率</th></tr></thead>
            <tbody>
              ${stats.map(s => `<tr>
                <td>${s.button_id}</td>
                <td><span class="badge badge-info">${s.style}</span></td>
                <td style="font-family:monospace;">${s.impressions}</td>
                <td style="font-family:monospace;">${s.clicks}</td>
                <td style="font-family:monospace; color:#10b981;">${(s.ctr*100).toFixed(2)}%</td>
              </tr>`).join('')}
            </tbody>
          </table>
        `}
      </div>
    `;
  } catch(e) { showToast('加载失败：' + (e.message || e), 'error'); document.getElementById('buttonStatsContent').innerHTML = '<p style="color:#6b7280;">暂无按钮点击数据</p>'; }
}

// ---- emoji面具检测 ----
let _emojiMaskKeywords = [];

async function loadEmojiMask() {
  try {
    const d = await api('/api/settings/emoji-mask');
    const data = d.data;
    _emojiMaskKeywords = data.keywords || [];
    const el = document.getElementById('emojimaskContent');
    if (!el) return;
    el.innerHTML = `
      <div class="card" style="margin-bottom:20px;">
        <h3 style="color:#fff; margin-bottom:16px;">emoji面具检测设置</h3>
        <div style="margin-bottom:16px;">
          <label style="display:flex; align-items:center; gap:8px; color:#94a3b8; font-size:13px; cursor:pointer;">
            <input type="checkbox" id="emEnable" ${data.enable?'checked':''} style="width:18px; height:18px;">
            启用emoji面具检测
          </label>
          <p style="color:#6b7280; font-size:12px; margin-top:4px;">开启后，入群用户名包含以下关键词的用户将被自动永久禁言</p>
        </div>
        <div style="margin-bottom:16px;">
          <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">新增关键词</label>
          <div style="display:flex; gap:8px;">
            <input id="emNewKeyword" type="text" placeholder="输入关键词" style="flex:1; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px;" onkeyup="if(event.key==='Enter') addEmojiKeyword()">
            <button class="btn btn-primary" onclick="addEmojiKeyword()">添加</button>
          </div>
        </div>
        <div style="margin-bottom:16px;">
          <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">当前关键词列表</label>
          <div id="emKeywordList" style="display:flex; flex-wrap:wrap; gap:8px; min-height:40px; padding:12px; background:#0f0f1a; border-radius:8px;">
            ${_emojiMaskKeywords.length === 0 ? '<span style="color:#6b7280; font-size:13px;">暂无关键词</span>' :
              _emojiMaskKeywords.map(kw => `
                <span style="display:inline-flex; align-items:center; gap:6px; padding:6px 12px; background:rgba(96,165,250,0.15); border:1px solid rgba(96,165,250,0.3); border-radius:6px; color:#60a5fa; font-size:13px;">
                  ${escHtml(kw)}
                  <span style="cursor:pointer; color:#ef4444; font-weight:bold;" onclick="removeEmojiKeyword('${escHtml(kw)}')">&times;</span>
                </span>
              `).join('')}
          </div>
        </div>
        <button class="btn btn-primary" onclick="saveEmojiMask()">保存配置</button>
      </div>
    `;
  } catch(e) { console.error(e); }
}

function addEmojiKeyword() {
  const input = document.getElementById('emNewKeyword');
  const kw = input.value.trim();
  if (!kw) return;
  if (_emojiMaskKeywords.includes(kw)) { showToast('关键词已存在', 'error'); return; }
  _emojiMaskKeywords.push(kw);
  input.value = '';
  // 重新渲染关键词列表
  const listEl = document.getElementById('emKeywordList');
  if (listEl) {
    listEl.innerHTML = _emojiMaskKeywords.map(kw => `
      <span style="display:inline-flex; align-items:center; gap:6px; padding:6px 12px; background:rgba(96,165,250,0.15); border:1px solid rgba(96,165,250,0.3); border-radius:6px; color:#60a5fa; font-size:13px;">
        ${escHtml(kw)}
        <span style="cursor:pointer; color:#ef4444; font-weight:bold;" onclick="removeEmojiKeyword('${escHtml(kw)}')">&times;</span>
      </span>
    `).join('');
  }
}

function removeEmojiKeyword(kw) {
  _emojiMaskKeywords = _emojiMaskKeywords.filter(k => k !== kw);
  const listEl = document.getElementById('emKeywordList');
  if (listEl) {
    if (_emojiMaskKeywords.length === 0) {
      listEl.innerHTML = '<span style="color:#6b7280; font-size:13px;">暂无关键词</span>';
    } else {
      listEl.innerHTML = _emojiMaskKeywords.map(k => `
        <span style="display:inline-flex; align-items:center; gap:6px; padding:6px 12px; background:rgba(96,165,250,0.15); border:1px solid rgba(96,165,250,0.3); border-radius:6px; color:#60a5fa; font-size:13px;">
          ${escHtml(k)}
          <span style="cursor:pointer; color:#ef4444; font-weight:bold;" onclick="removeEmojiKeyword('${escHtml(k)}')">&times;</span>
        </span>
      `).join('');
    }
  }
}

async function saveEmojiMask() {
  const data = {
    keywords: _emojiMaskKeywords,
    enable: document.getElementById('emEnable').checked
  };
  try {
    const r = await api('/api/settings/emoji-mask', { method: 'POST', body: JSON.stringify(data) });
    showToast(r.msg || '保存成功', 'success');
  } catch(e) { showToast('保存失败', 'error'); }
}

// 【v4.17.0新增】关键词触发规则管理
let _keywordTriggers = [];
let _topicReplyStats = [];

async function loadKeywordTriggers() {
  try {
    const d = await api('/api/keywords');
    _keywordTriggers = d.data.triggers || [];
    _topicReplyStats = d.data.topic_stats || [];
    const el = document.getElementById('keywordTriggersContent');
    if (!el) return;
    const typeNames = { static: '静态回复', ai: 'AI智能回复', action: '动作执行' };
    el.innerHTML = `
      <div class="card" style="margin-bottom:20px;">
        <h3 style="color:#fff; margin-bottom:6px;">关键话题近30天</h3>
        <p style="color:#94a3b8; font-size:13px; margin-bottom:14px;">只统计命中次数与润色结果，不保存用户原话。</p>
        <div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px;">
          ${_topicReplyStats.length === 0
            ? '<div style="color:#6b7280;">暂无命中数据</div>'
            : _topicReplyStats.map(s => `
              <div style="padding:14px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.08); border-radius:10px;">
                <div style="font-size:16px; color:#fff; margin-bottom:8px;">${escHtml(s.topic)}</div>
                <div style="font-size:13px; color:#cbd5e1;">命中 ${s.total} 次 · ${s.users} 人</div>
                <div style="font-size:12px; color:#94a3b8; margin-top:4px;">AI润色 ${s.polished} · 底稿兜底 ${s.template}</div>
                <div style="font-size:11px; color:#64748b; margin-top:6px;">${s.last_hit_at ? new Date(s.last_hit_at * 1000).toLocaleString() : '尚无时间'}</div>
              </div>
            `).join('')}
        </div>
      </div>
      <div class="card" style="margin-bottom:20px;">
        <h3 style="color:#fff; margin-bottom:16px;">新增规则</h3>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:12px;">
          <div>
            <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">关键词</label>
            <input id="ktKeyword" type="text" placeholder="如：帮助" style="width:100%; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px;">
          </div>
          <div>
            <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">回复类型</label>
            <select id="ktType" style="width:100%; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px;">
              <option value="static">静态回复</option>
              <option value="ai">AI智能回复</option>
              <option value="action">动作执行</option>
            </select>
          </div>
        </div>
        <div style="margin-bottom:12px;">
          <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">回复内容</label>
          <textarea id="ktReply" placeholder="输入回复文本（AI模式则为提示词，action模式为动作命令）" style="width:100%; min-height:60px; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px; resize:vertical;"></textarea>
        </div>
        <div style="margin-bottom:12px;">
          <label style="color:#94a3b8; font-size:13px; display:block; margin-bottom:6px;">动作类型（仅reply_type=action时有效）</label>
          <input id="ktAction" type="text" placeholder="如：mute, kick, warn" style="width:100%; padding:10px; background:#1e1e2e; border:1px solid rgba(255,255,255,0.1); border-radius:8px; color:#e2e8f0; font-size:14px;">
        </div>
        <button class="btn btn-primary" onclick="addKeywordTrigger()">添加规则</button>
      </div>
      <div class="card">
        <h3 style="color:#fff; margin-bottom:16px;">现有规则（${_keywordTriggers.length}条）</h3>
        <div style="overflow-x:auto;">
          <table style="width:100%; border-collapse:collapse; color:#e2e8f0; font-size:13px;">
            <thead>
              <tr style="border-bottom:1px solid rgba(255,255,255,0.1);">
                <th style="padding:10px; text-align:left; color:#94a3b8;">ID</th>
                <th style="padding:10px; text-align:left; color:#94a3b8;">关键词</th>
                <th style="padding:10px; text-align:left; color:#94a3b8;">类型</th>
                <th style="padding:10px; text-align:left; color:#94a3b8;">回复内容</th>
                <th style="padding:10px; text-align:left; color:#94a3b8;">状态</th>
                <th style="padding:10px; text-align:left; color:#94a3b8;">操作</th>
              </tr>
            </thead>
            <tbody>
              ${_keywordTriggers.length === 0 ? '<tr><td colspan="6" style="padding:20px; text-align:center; color:#6b7280;">暂无规则</td></tr>' :
                _keywordTriggers.map(t => `
                  <tr style="border-bottom:1px solid rgba(255,255,255,0.05);">
                    <td style="padding:10px;">${t.id}</td>
                    <td style="padding:10px;">${escHtml(t.keyword)}</td>
                    <td style="padding:10px;"><span class="badge badge-info">${typeNames[t.reply_type] || t.reply_type}</span></td>
                    <td style="padding:10px; max-width:250px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escHtml(t.reply_text)}</td>
                    <td style="padding:10px;">
                      <span style="cursor:pointer; color:${t.enabled?'#10b981':'#ef4444'};" onclick="toggleKeywordTrigger(${t.id}, ${t.enabled ? 'false' : 'true'})">
                        ${t.enabled ? '🟢 启用' : '🔴 禁用'}
                      </span>
                    </td>
                    <td style="padding:10px;">
                      <button class="btn btn-sm btn-danger" onclick="deleteKeywordTrigger(${t.id})">删除</button>
                    </td>
                  </tr>
                `).join('')}
            </tbody>
          </table>
        </div>
      </div>
    `;
  } catch(e) { console.error(e); }
}

async function addKeywordTrigger() {
  const keyword = document.getElementById('ktKeyword').value.trim();
  const reply_text = document.getElementById('ktReply').value.trim();
  const reply_type = document.getElementById('ktType').value;
  const action_type = document.getElementById('ktAction').value.trim();
  if (!keyword || !reply_text) { showToast('关键词和回复内容不能为空', 'error'); return; }
  try {
    const r = await api('/api/keywords', {
      method: 'POST',
      body: JSON.stringify({ keyword, reply_text, reply_type, action_type })
    });
    showToast(r.msg || '添加成功', 'success');
    loadKeywordTriggers();
  } catch(e) { showToast('添加失败', 'error'); }
}

async function deleteKeywordTrigger(id) {
  if (!confirm('确定要删除此规则吗？')) return;
  try {
    const r = await api('/api/keywords/' + id, { method: 'DELETE' });
    showToast(r.msg || '删除成功', 'success');
    loadKeywordTriggers();
  } catch(e) { showToast('删除失败', 'error'); }
}

async function toggleKeywordTrigger(id, enabled) {
  try {
    const r = await api('/api/keywords/' + id, {
      method: 'PUT',
      body: JSON.stringify({ enabled: enabled })
    });
    showToast(r.msg || '更新成功', 'success');
    loadKeywordTriggers();
  } catch(e) { showToast('更新失败', 'error'); }
}

function renderApp() {
  document.getElementById('app').innerHTML = `
    <div class="dashboard">
      <aside class="sidebar">
        <div class="sidebar-header">
          <div class="sidebar-logo">
            <div class="sidebar-logo-icon">🤖</div>
            <div class="sidebar-logo-text">
              <h1>Mory Assistant</h1>
              <span id="sidebarVersion">加载中</span>
            </div>
          </div>
        </div>
        <nav class="sidebar-nav">
          <div class="nav-section">
            <div class="nav-section-title">数据中心</div>
            <div class="nav-item active" onclick="switchTab('overview')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <rect x="3" y="3" width="7" height="7" rx="1"/>
                <rect x="14" y="3" width="7" height="7" rx="1"/>
                <rect x="3" y="14" width="7" height="7" rx="1"/>
                <rect x="14" y="14" width="7" height="7" rx="1"/>
              </svg>
              数据概览
            </div>
            <div class="nav-item" onclick="switchTab('users')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
                <circle cx="9" cy="7" r="4"/>
                <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
                <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
              </svg>
              用户管理
            </div>
            <div class="nav-item" onclick="switchTab('groups')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>
              </svg>
              群组数据
            </div>
          </div>
          <div class="nav-section">
            <div class="nav-section-title">运行监控</div>
            <div class="nav-item" onclick="switchTab('status')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M22 12h-4l-3 9L9 3l-3 9H2"/>
              </svg>
              运行状态
            </div>
            <div class="nav-item" onclick="switchTab('models')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <rect x="4" y="4" width="16" height="16" rx="2"/>
                <rect x="9" y="9" width="6" height="6"/>
                <line x1="9" y1="2" x2="9" y2="4"/>
                <line x1="15" y1="2" x2="15" y2="4"/>
                <line x1="9" y1="20" x2="9" y2="22"/>
                <line x1="15" y1="20" x2="15" y2="22"/>
              </svg>
              模型中心
            </div>
            <div class="nav-item" onclick="switchTab('tasks')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <circle cx="12" cy="12" r="10"/>
                <polyline points="12 6 12 12 16 14"/>
              </svg>
              定时任务
            </div>
            <div class="nav-item" onclick="switchTab('groupmgr')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
              </svg>
              群管设置
            </div>
            <div class="nav-item" onclick="switchTab('feedback')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3H14zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
              </svg>
              用户反馈
            </div>
            <div class="nav-item" onclick="switchTab('userprofile')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
                <circle cx="9" cy="7" r="4"/>
                <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
                <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
              </svg>
              用户画像
            </div>
            <div class="nav-item" onclick="switchTab('attribution')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M3 3v18h18"/>
                <path d="M18 17V9"/>
                <path d="M13 17V5"/>
                <path d="M8 17v-3"/>
              </svg>
              转化归因分析
            </div>
            <div class="nav-item" onclick="switchTab('funnel')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M22 3H2l8 9.46V19l4 2v-8.54L22 3z"/>
              </svg>
              转化漏斗
            </div>
            <div class="nav-item" onclick="switchTab('modelperf')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M12 2L2 7l10 5 10-5-10-5z"/>
                <path d="M2 17l10 5 10-5"/>
                <path d="M2 12l10 5 10-5"/>
              </svg>
              大模型效能对比
            </div>
          </div>
          <div class="nav-section">
            <div class="nav-section-title">功能配置</div>
            <div class="nav-item" onclick="switchTab('verification')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
                <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
              </svg>
              验证码配置
            </div>
            <div class="nav-item" onclick="switchTab('welcome')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
              </svg>
              欢迎定制
            </div>
            <div class="nav-item" onclick="switchTab('nightmode')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
              </svg>
              夜间模式
            </div>
            <div class="nav-item" onclick="switchTab('broadcasts')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M22 12h-4l-3 9L9 3l-3 9H2"/>
              </svg>
              定点播报
            </div>
            <div class="nav-item" onclick="switchTab('broadcast-format')">📝 播报格式（Rich）</div>
            <div class="nav-item" onclick="switchTab('button-style')">🎨 彩色按钮样式</div>
            <div class="nav-item" onclick="switchTab('custom-emoji')">😀 Custom Emoji 池</div>
            <div class="nav-item" onclick="switchTab('user-profile')">👤 用户画像</div>
            <div class="nav-item" onclick="switchTab('ab-test')">🧪 A/B 测试</div>
            <div class="nav-item" onclick="switchTab('button-stats')">📊 按钮点击统计</div>
            <div class="nav-item" onclick="switchTab('federation')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <circle cx="12" cy="12" r="10"/>
                <line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/>
              </svg>
              联邦封禁
            </div>
            <div class="nav-item" onclick="switchTab('emojimask')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <circle cx="12" cy="12" r="10"/>
                <path d="M12 8v4"/>
                <path d="M12 16h.01"/>
              </svg>
              emoji面具
            </div>
            <div class="nav-item" onclick="switchTab('keywordtriggers')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>
                <rect x="8" y="2" width="8" height="4" rx="1"/>
                <line x1="9" y1="12" x2="15" y2="12"/>
                <line x1="9" y1="16" x2="13" y2="16"/>
              </svg>
              关键词触发
            </div>
          </div>
          <div class="nav-section">
            <div class="nav-section-title">⚙️ 设置面板完全体</div>
            <div class="nav-item" onclick="switchTab('warning')">🛡️ 警告配置</div>
            <div class="nav-item" onclick="switchTab('slowmode')">🐌 慢速模式</div>
            <div class="nav-item" onclick="switchTab('report')">📢 举报配置</div>
            <div class="nav-item" onclick="switchTab('votekick')">🗳️ 投票踢人</div>
            <div class="nav-item" onclick="switchTab('antiflood')">💧 反刷屏</div>
            <div class="nav-item" onclick="switchTab('antiraid')">🚨 反突袭</div>
            <div class="nav-item" onclick="switchTab('antidelete')">📝 反撤回</div>
            <div class="nav-item" onclick="switchTab('nsfw')">🔞 NSFW检测</div>
            <div class="nav-item" onclick="switchTab('blindbox')">🎁 盲盒配置</div>
            <div class="nav-item" onclick="switchTab('luckywheel')">🎡 转盘配置</div>
            <div class="nav-item" onclick="switchTab('redpacket')">🧧 红包配置</div>
            <div class="nav-item" onclick="switchTab('lottery')">🎰 抽奖配置</div>
            <div class="nav-item" onclick="switchTab('checkin')">📋 签到配置</div>
            <div class="nav-item" onclick="switchTab('shop')">🛒 商城配置</div>
            <div class="nav-item" onclick="switchTab('coupon')">🎟️ 优惠券配置</div>
            <div class="nav-item" onclick="switchTab('tip')">💰 打赏配置</div>
            <div class="nav-item" onclick="switchTab('dailyquest')">📝 每日任务</div>
            <div class="nav-item" onclick="switchTab('achievement')">🏆 成就配置</div>
            <div class="nav-item" onclick="switchTab('pointsdecay')">📉 积分衰减</div>
            <div class="nav-item" onclick="switchTab('afk')">💤 AFK配置</div>
            <div class="nav-item" onclick="switchTab('antichannel')">🚫 反频道转发</div>
            <div class="nav-item" onclick="switchTab('cas')">🛡️ CAS检查</div>
            <div class="nav-item" onclick="switchTab('cleanservice')">🧹 服务消息清理</div>
            <div class="nav-item" onclick="switchTab('autoreply')">🤖 自动回复</div>
            <div class="nav-item" onclick="switchTab('messagelocks')">🔒 消息锁</div>
            <div class="nav-item" onclick="switchTab('adspam')">🚫 广告防刷</div>
            <div class="nav-item" onclick="switchTab('inactiveclean')">👋 不活跃清理</div>
            <div class="nav-item" onclick="switchTab('greeting')">🌅 问候配置</div>
            <div class="nav-item" onclick="switchTab('mystic')">☯️ 传统文化播报</div>
            <div class="nav-item" onclick="switchTab('exchangerate')">💱 汇率配置</div>
            <div class="nav-item" onclick="switchTab('visualdashboard')">📊 可视化面板</div>
            <div class="nav-item" onclick="switchTab('language')">🌐 语言设置</div>
            <div class="nav-item" onclick="switchTab('spamaction')">⚡ 广告动作</div>
            <div class="nav-item" onclick="switchTab('goodbye')">👋 退群消息</div>
            <div class="nav-item" onclick="switchTab('rules')">📜 群规配置</div>
            <div class="nav-item" onclick="switchTab('games')">🎮 游戏配置</div>
          </div>
          <div class="nav-section">
            <div class="nav-section-title">🤖 AI模型</div>
            <div class="nav-item" onclick="switchTab('aimodel')">🧠 模型参数</div>
            <div class="nav-item" onclick="switchTab('persona')">💬 人设编辑</div>
            <div class="nav-item" onclick="switchTab('replystyle')">🍼 风格样本审核</div>
          </div>
          <div class="nav-section">
            <div class="nav-section-title">⚡ 高级</div>
            <div class="nav-item" onclick="switchTab('botcore')">🔧 Bot核心</div>
            <div class="nav-item" onclick="switchTab('pricing')">💲 定价管理</div>
          </div>
          <div class="nav-section">
            <div class="nav-section-title">系统</div>
            <div class="nav-item" onclick="switchTab('config')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <circle cx="12" cy="12" r="3"/>
                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
              </svg>
              系统配置
            </div>
            <div class="nav-item" onclick="switchTab('reports')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
                <line x1="16" y1="13" x2="8" y2="13"/>
                <line x1="16" y1="17" x2="8" y2="17"/>
                <polyline points="10 9 9 9 8 9"/>
              </svg>
              运营报表
            </div>
            <div class="nav-item" onclick="switchTab('logs')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
                <line x1="16" y1="13" x2="8" y2="13"/>
                <line x1="16" y1="17" x2="8" y2="17"/>
              </svg>
              日志查看
            </div>
            <div class="nav-item" onclick="switchTab('helpcenter')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <circle cx="12" cy="12" r="10"/>
                <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
                <line x1="12" y1="17" x2="12.01" y2="17"/>
              </svg>
              帮助中心
            </div>
          </div>
        </nav>
      </aside>
      <main class="main-content">
        <header class="top-bar">
          <div class="top-bar-left">
            <button class="icon-btn" onclick="toggleSidebar()">☰</button>
            <h1 class="page-title">数据概览</h1>
          </div>
          <div class="top-bar-right">
            <span id="viewerBadge" style="display:none; background:rgba(234,179,8,0.15); color:#eab308; padding:4px 12px; border-radius:20px; font-size:12px; font-weight:500;">只读模式</span>
            <div class="status-pill" id="botStatus">
              <span class="status-dot" id="statusDot"></span>
              <span id="botStatusText">加载中</span>
            </div>
            <button class="icon-btn" onclick="doLogout()" title="退出登录">🚪</button>
          </div>
        </header>
        <div class="page-content" id="mainContent"></div>
      </main>
    </div>
  `;
  renderPage();
  loadVersion();
}

function toggleSidebar() {
  document.querySelector('.sidebar').classList.toggle('open');
}

async function init() {
  const isAuthenticated = await checkAuth();
  if (isAuthenticated) {
    renderApp();
    if (_userRole === 'viewer') {
      const style = document.createElement('style');
      style.textContent = '.admin-only { display: none !important; }';
      document.head.appendChild(style);
      const badge = document.getElementById('viewerBadge');
      if (badge) badge.style.display = 'inline-block';
      applyViewerRestrictions();
      const observer = new MutationObserver(() => applyViewerRestrictions());
      observer.observe(document.getElementById('app'), { childList: true, subtree: true });
    }
  }
}

function applyViewerRestrictions() {
  document.querySelectorAll('button:not(.admin-only-checked)').forEach(btn => {
    btn.classList.add('admin-only-checked');
    const oc = (btn.getAttribute('onclick') || '');
    if (/save|add|delete|remove|封禁|添加|删除|保存|应用|quickSaveConfig/.test(oc)) {
      btn.classList.add('admin-only');
    }
  });
  document.querySelectorAll('input:not(.viewer-locked),textarea:not(.viewer-locked),select:not(.viewer-locked)').forEach(el => {
    el.classList.add('viewer-locked');
    const type = (el.type || '').toLowerCase();
    if (type === 'checkbox' || type === 'number' || type === 'text' || type === 'password' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') {
      if (!el.id || el.id !== 'password') {
        el.disabled = true;
      }
    }
  });
}

// ============ 设置面板完全体 加载/保存函数 ============

async function loadWarningConfig() {
  try {
    const d = await api('/api/settings/warning'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('warningContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>警告设置</h3>
      <div class="form-group"><label>警告阈值（次）</label><input type="number" id="warnLimit" value="${cfg.limit}" min="1" max="10" class="input-field"></div>
      <div class="form-group"><label>处罚方式</label><select id="warnAction" class="input-field"><option value="mute" ${cfg.action==='mute'?'selected':''}>禁言</option><option value="ban" ${cfg.action==='ban'?'selected':''}>封禁</option><option value="kick" ${cfg.action==='kick'?'selected':''}>踢出</option></select></div>
      <div class="form-group"><label>禁言时长（秒）</label><input type="number" id="warnDuration" value="${cfg.duration}" min="60" class="input-field"></div>
      <button class="btn btn-primary" onclick="saveWarningConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('warningContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveWarningConfig() {
  try {
    const res = await api('/api/settings/warning', { method: 'POST', body: JSON.stringify({ limit: parseInt(document.getElementById('warnLimit').value), action: document.getElementById('warnAction').value, duration: parseInt(document.getElementById('warnDuration').value) }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadWarningConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadSlowmodeConfig() {
  try {
    const d = await api('/api/settings/slowmode'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('slowmodeContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>慢速模式</h3>
      <div class="toggle-row"><span>启用慢速模式</span><label class="toggle-switch"><input type="checkbox" id="slowEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="form-group"><label>消息间隔（秒）</label><input type="number" id="slowInterval" value="${cfg.interval}" min="0" class="input-field"></div>
      <button class="btn btn-primary" onclick="saveSlowmodeConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('slowmodeContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveSlowmodeConfig() {
  try {
    const res = await api('/api/settings/slowmode', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('slowEnable').checked, interval: parseInt(document.getElementById('slowInterval').value) }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadSlowmodeConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadReportConfig() {
  try {
    const d = await api('/api/settings/report'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('reportContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>举报设置</h3>
      <div class="toggle-row"><span>启用举报</span><label class="toggle-switch"><input type="checkbox" id="rptEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="form-group"><label>冷却时间（秒）</label><input type="number" id="rptCooldown" value="${cfg.cooldown}" min="0" class="input-field"></div>
      <button class="btn btn-primary" onclick="saveReportConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('reportContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveReportConfig() {
  try {
    const res = await api('/api/settings/report', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('rptEnable').checked, cooldown: parseInt(document.getElementById('rptCooldown').value) }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadReportConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadVotekickConfig() {
  try {
    const d = await api('/api/settings/votekick'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('votekickContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>投票踢人</h3>
      <div class="form-group"><label>最低赞成票数</label><input type="number" id="vkMinYes" value="${cfg.min_yes}" min="2" class="input-field"></div>
      <div class="form-group"><label>最低赞成比例</label><input type="number" id="vkMinRatio" value="${cfg.min_ratio}" min="0" max="1" step="0.1" class="input-field"></div>
      <div class="form-group"><label>投票时长（秒）</label><input type="number" id="vkDuration" value="${cfg.duration}" min="30" class="input-field"></div>
      <button class="btn btn-primary" onclick="saveVotekickConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('votekickContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveVotekickConfig() {
  try {
    const res = await api('/api/settings/votekick', { method: 'POST', body: JSON.stringify({ min_yes: parseInt(document.getElementById('vkMinYes').value), min_ratio: parseFloat(document.getElementById('vkMinRatio').value), duration: parseInt(document.getElementById('vkDuration').value) }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadVotekickConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadAntifloodConfig() {
  try {
    const d = await api('/api/settings/antiflood'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('antifloodContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>反刷屏</h3>
      <div class="toggle-row"><span>启用反刷屏</span><label class="toggle-switch"><input type="checkbox" id="afEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="form-group"><label>每分钟消息数上限</label><input type="number" id="afMsgs" value="${cfg.messages_per_minute}" min="1" class="input-field"></div>
      <div class="form-group"><label>检测窗口（秒）</label><input type="number" id="afWindow" value="${cfg.window || 5}" min="1" class="input-field"></div>
      <div class="form-group"><label>触发阈值（条）</label><input type="number" id="afThreshold" value="${cfg.threshold || 5}" min="1" class="input-field"></div>
      <div class="form-group"><label>禁言时长（秒）</label><input type="number" id="afMuteDuration" value="${cfg.mute_duration || 60}" min="1" class="input-field"></div>
      <div class="form-group"><label>超限处罚时长（分钟）</label><input type="number" id="afBan" value="${cfg.ban_minutes}" min="1" class="input-field"></div>
      <div class="form-group"><label>说明</label><div class="hint-text">这页现在会同时保存消息频率限制和反刷屏引擎参数，不再出现改了一个配置、另一个模块没跟上的情况。</div></div>
      <button class="btn btn-primary" onclick="saveAntifloodConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('antifloodContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveAntifloodConfig() {
  try {
    const res = await api('/api/settings/antiflood', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('afEnable').checked, messages_per_minute: parseInt(document.getElementById('afMsgs').value), window: parseInt(document.getElementById('afWindow').value), threshold: parseInt(document.getElementById('afThreshold').value), mute_duration: parseInt(document.getElementById('afMuteDuration').value), ban_minutes: parseInt(document.getElementById('afBan').value) }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadAntifloodConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadAntiraidConfig() {
  try {
    const d = await api('/api/settings/anti-raid'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('antiraidContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>反突袭</h3>
      <div class="toggle-row"><span>启用反突袭</span><label class="toggle-switch"><input type="checkbox" id="arEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="form-group"><label>触发阈值（人数）</label><input type="number" id="arThreshold" value="${cfg.threshold}" min="1" class="input-field"></div>
      <div class="form-group"><label>检测窗口（秒）</label><input type="number" id="arWindow" value="${cfg.window}" min="10" class="input-field"></div>
      <div class="form-group"><label>锁定持续（秒）</label><input type="number" id="arLock" value="${cfg.lock_duration || 300}" min="60" class="input-field"></div>
      <button class="btn btn-primary" onclick="saveAntiraidConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('antiraidContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveAntiraidConfig() {
  try {
    const res = await api('/api/settings/anti-raid', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('arEnable').checked, threshold: parseInt(document.getElementById('arThreshold').value), window: parseInt(document.getElementById('arWindow').value), lock_duration: parseInt(document.getElementById('arLock').value) }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadAntiraidConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadAntideleteConfig() {
  try {
    const d = await api('/api/settings/antidelete'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('antideleteContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>反撤回</h3>
      <div class="toggle-row"><span>启用反撤回</span><label class="toggle-switch"><input type="checkbox" id="adEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="toggle-row"><span>通知管理员</span><label class="toggle-switch"><input type="checkbox" id="adNotify" ${cfg.notify_admin?'checked':''}><span class="slider"></span></label></div>
      <button class="btn btn-primary" onclick="saveAntideleteConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('antideleteContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveAntideleteConfig() {
  try {
    const res = await api('/api/settings/antidelete', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('adEnable').checked, notify_admin: document.getElementById('adNotify').checked }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadAntideleteConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadNsfwConfig() {
  try {
    const d = await api('/api/settings/nsfw'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('nsfwContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>NSFW检测</h3>
      <div class="toggle-row"><span>启用NSFW检测</span><label class="toggle-switch"><input type="checkbox" id="nsfwEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="form-group"><label>API密钥</label><input type="password" id="nsfwApiKey" value="${cfg.api_key || ''}" class="input-field"></div>
      <div class="form-group"><label>检测阈值（0-1）</label><input type="number" id="nsfwThreshold" value="${cfg.threshold}" min="0" max="1" step="0.05" class="input-field"></div>
      <button class="btn btn-primary" onclick="saveNsfwConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('nsfwContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveNsfwConfig() {
  try {
    const res = await api('/api/settings/nsfw', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('nsfwEnable').checked, api_key: document.getElementById('nsfwApiKey').value, threshold: parseFloat(document.getElementById('nsfwThreshold').value) }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadNsfwConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadBlindboxConfig() {
  try {
    const d = await api('/api/settings/blind-box'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('blindboxContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>盲盒设置</h3>
      <div class="toggle-row"><span>启用盲盒</span><label class="toggle-switch"><input type="checkbox" id="bbEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="form-group"><label>盲盒成本（积分）</label><input type="number" id="bbCost" value="${cfg.cost}" min="1" class="input-field"></div>
      <button class="btn btn-primary" onclick="saveBlindboxConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('blindboxContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveBlindboxConfig() {
  try {
    const res = await api('/api/settings/blind-box', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('bbEnable').checked, cost: parseInt(document.getElementById('bbCost').value) }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadBlindboxConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadLuckywheelConfig() {
  try {
    const d = await api('/api/settings/lucky-wheel'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('luckywheelContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>转盘设置</h3>
      <div class="toggle-row"><span>启用转盘</span><label class="toggle-switch"><input type="checkbox" id="lwEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="form-group"><label>转盘成本（积分）</label><input type="number" id="lwCost" value="${cfg.cost}" min="1" class="input-field"></div>
      <div class="form-group"><label>免费次数</label><input type="number" id="lwFree" value="${cfg.free_spins}" min="0" class="input-field"></div>
      <button class="btn btn-primary" onclick="saveLuckywheelConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('luckywheelContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveLuckywheelConfig() {
  try {
    const res = await api('/api/settings/lucky-wheel', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('lwEnable').checked, cost: parseInt(document.getElementById('lwCost').value), free_spins: parseInt(document.getElementById('lwFree').value) }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadLuckywheelConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadRedpacketConfig() {
  try {
    const d = await api('/api/settings/redpacket'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('redpacketContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>红包设置</h3>
      <div class="toggle-row"><span>启用红包</span><label class="toggle-switch"><input type="checkbox" id="rpEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="form-group"><label>最小金额</label><input type="number" id="rpMin" value="${cfg.min_amount}" min="1" class="input-field"></div>
      <div class="form-group"><label>最大金额</label><input type="number" id="rpMax" value="${cfg.max_amount}" min="1" class="input-field"></div>
      <button class="btn btn-primary" onclick="saveRedpacketConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('redpacketContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveRedpacketConfig() {
  try {
    const res = await api('/api/settings/redpacket', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('rpEnable').checked, min_amount: parseInt(document.getElementById('rpMin').value), max_amount: parseInt(document.getElementById('rpMax').value) }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadRedpacketConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadLotteryConfig() {
  try {
    const d = await api('/api/settings/lottery'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('lotteryContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>抽奖设置</h3>
      <div class="toggle-row"><span>启用抽奖</span><label class="toggle-switch"><input type="checkbox" id="lotEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="form-group"><label>参与成本（积分）</label><input type="number" id="lotCost" value="${cfg.cost || 50}" min="1" class="input-field"></div>
      <button class="btn btn-primary" onclick="saveLotteryConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('lotteryContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveLotteryConfig() {
  try {
    const res = await api('/api/settings/lottery', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('lotEnable').checked, cost: parseInt(document.getElementById('lotCost').value) }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadLotteryConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadCheckinConfig() {
  try {
    const d = await api('/api/settings/checkin'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('checkinContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>签到设置</h3>
      <div class="toggle-row"><span>启用签到</span><label class="toggle-switch"><input type="checkbox" id="ckEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="form-group"><label>基础积分</label><input type="number" id="ckBase" value="${cfg.base_points}" min="1" class="input-field"></div>
      <div class="form-group"><label>连续3天奖励</label><input type="number" id="ckStreak3" value="${(cfg.streak_bonus && cfg.streak_bonus['3']) || 5}" min="0" class="input-field"></div>
      <div class="form-group"><label>连续7天奖励</label><input type="number" id="ckStreak7" value="${(cfg.streak_bonus && cfg.streak_bonus['7']) || 15}" min="0" class="input-field"></div>
      <button class="btn btn-primary" onclick="saveCheckinConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('checkinContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveCheckinConfig() {
  try {
    const res = await api('/api/settings/checkin', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('ckEnable').checked, base_points: parseInt(document.getElementById('ckBase').value), streak_bonus: {"3": parseInt(document.getElementById('ckStreak3').value), "7": parseInt(document.getElementById('ckStreak7').value)} }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadCheckinConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadShopConfig() {
  try {
    const d = await api('/api/settings/shop'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('shopContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>商城设置</h3>
      <div class="toggle-row"><span>启用商城</span><label class="toggle-switch"><input type="checkbox" id="shopEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <button class="btn btn-primary" onclick="saveShopConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('shopContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveShopConfig() {
  try {
    const res = await api('/api/settings/shop', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('shopEnable').checked }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadShopConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadCouponConfig() {
  try {
    const d = await api('/api/settings/coupon'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('couponContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>优惠券设置</h3>
      <div class="toggle-row"><span>启用优惠券</span><label class="toggle-switch"><input type="checkbox" id="cpnEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <button class="btn btn-primary" onclick="saveCouponConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('couponContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveCouponConfig() {
  try {
    const res = await api('/api/settings/coupon', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('cpnEnable').checked }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadCouponConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadTipConfig() {
  try {
    const d = await api('/api/settings/tip'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('tipContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>打赏设置</h3>
      <div class="toggle-row"><span>启用打赏</span><label class="toggle-switch"><input type="checkbox" id="tipEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="form-group"><label>最低打赏金额</label><input type="number" id="tipMin" value="${cfg.min_amount}" min="1" class="input-field"></div>
      <button class="btn btn-primary" onclick="saveTipConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('tipContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveTipConfig() {
  try {
    const res = await api('/api/settings/tip', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('tipEnable').checked, min_amount: parseInt(document.getElementById('tipMin').value) }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadTipConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadDailyquestConfig() {
  try {
    const d = await api('/api/settings/daily-quest'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('dailyquestContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>每日任务</h3>
      <div class="toggle-row"><span>启用每日任务</span><label class="toggle-switch"><input type="checkbox" id="dqEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <button class="btn btn-primary" onclick="saveDailyquestConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('dailyquestContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveDailyquestConfig() {
  try {
    const res = await api('/api/settings/daily-quest', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('dqEnable').checked }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadDailyquestConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadAchievementConfig() {
  try {
    const d = await api('/api/settings/achievements'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('achievementContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>成就设置</h3>
      <div class="toggle-row"><span>启用成就系统</span><label class="toggle-switch"><input type="checkbox" id="achEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <button class="btn btn-primary" onclick="saveAchievementConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('achievementContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveAchievementConfig() {
  try {
    const res = await api('/api/settings/achievements', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('achEnable').checked }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadAchievementConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadPointsdecayConfig() {
  try {
    const d = await api('/api/settings/points-decay'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('pointsdecayContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>积分衰减</h3>
      <div class="toggle-row"><span>启用积分衰减</span><label class="toggle-switch"><input type="checkbox" id="pdEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="form-group"><label>衰减比例</label><input type="number" id="pdRate" value="${cfg.rate}" min="0" max="1" step="0.01" class="input-field"></div>
      <div class="form-group"><label>最低保留积分</label><input type="number" id="pdMin" value="${cfg.minimum}" min="0" class="input-field"></div>
      <button class="btn btn-primary" onclick="savePointsdecayConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('pointsdecayContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function savePointsdecayConfig() {
  try {
    const res = await api('/api/settings/points-decay', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('pdEnable').checked, rate: parseFloat(document.getElementById('pdRate').value), minimum: parseInt(document.getElementById('pdMin').value) }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadPointsdecayConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadAfkConfig() {
  try {
    const d = await api('/api/settings/afk'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('afkContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>AFK设置</h3>
      <div class="toggle-row"><span>启用AFK</span><label class="toggle-switch"><input type="checkbox" id="afkEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="form-group"><label>自动回复消息</label><textarea id="afkReply" class="input-field" rows="2">${cfg.auto_reply || ''}</textarea></div>
      <button class="btn btn-primary" onclick="saveAfkConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('afkContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveAfkConfig() {
  try {
    const res = await api('/api/settings/afk', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('afkEnable').checked, auto_reply: document.getElementById('afkReply').value }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadAfkConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadAntichannelConfig() {
  try {
    const d = await api('/api/settings/antichannel'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('antichannelContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>反频道转发</h3>
      <div class="toggle-row"><span>启用反频道转发</span><label class="toggle-switch"><input type="checkbox" id="acEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <button class="btn btn-primary" onclick="saveAntichannelConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('antichannelContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveAntichannelConfig() {
  try {
    const res = await api('/api/settings/antichannel', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('acEnable').checked }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadAntichannelConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadCasConfig() {
  try {
    const d = await api('/api/settings/cas'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('casContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>CAS检查</h3>
      <div class="toggle-row"><span>启用CAS检查</span><label class="toggle-switch"><input type="checkbox" id="casEnable" ${cfg.cas_enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="toggle-row"><span>启用SpamWatch</span><label class="toggle-switch"><input type="checkbox" id="casSpamwatch" ${cfg.spamwatch_enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="form-group"><label>SpamWatch Token</label><input type="password" id="casSpamwatchToken" value="${cfg.spamwatch_token || ''}" class="input-field" placeholder="留空则保持关闭"></div>
      <div class="form-group"><label>说明</label><div class="hint-text">这里保留当前真实接线的 CAS 与 SpamWatch 开关。未实际落地的“自动封禁/处理方式”旧字段已移除。</div></div>
      <button class="btn btn-primary" onclick="saveCasConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('casContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveCasConfig() {
  try {
    const res = await api('/api/settings/cas', { method: 'POST', body: JSON.stringify({ cas_enabled: document.getElementById('casEnable').checked, spamwatch_enabled: document.getElementById('casSpamwatch').checked, spamwatch_token: document.getElementById('casSpamwatchToken').value }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadCasConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadCleanserviceConfig() {
  try {
    const d = await api('/api/settings/clean-service'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('cleanserviceContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>服务消息清理</h3>
      <div class="toggle-row"><span>启用清理</span><label class="toggle-switch"><input type="checkbox" id="csEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <button class="btn btn-primary" onclick="saveCleanserviceConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('cleanserviceContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveCleanserviceConfig() {
  try {
    const res = await api('/api/settings/clean-service', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('csEnable').checked }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadCleanserviceConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadAutoreplyConfig() {
  try {
    const d = await api('/api/settings/autoreply'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('autoreplyContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>自动回复</h3>
      <div class="toggle-row"><span>启用自动回复</span><label class="toggle-switch"><input type="checkbox" id="arEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <button class="btn btn-primary" onclick="saveAutoreplyConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('autoreplyContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveAutoreplyConfig() {
  try {
    const res = await api('/api/settings/autoreply', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('arEnable').checked }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadAutoreplyConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadAdSpamConfig() {
  try {
    const d = await api('/api/settings/ad-spam'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('adspamContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>广告检测</h3>
      <div class="toggle-row"><span>启用广告检测</span><label class="toggle-switch"><input type="checkbox" id="adsEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="form-group"><label>检测灵敏度（1-5）</label><input type="range" id="adsSens" value="${cfg.sensitivity}" min="1" max="5" class="input-field"><span id="adsSensVal">${cfg.sensitivity}</span></div>
      <div class="form-group"><label>说明</label><div class="hint-text">广告词库已由系统规则和专门词库维护，这里只保留真正生效的总开关和灵敏度。</div></div>
      <button class="btn btn-primary" onclick="saveAdSpamConfig()">保存设置</button></div>`;
    document.getElementById('adsSens').addEventListener('input', function(){ document.getElementById('adsSensVal').textContent = this.value; });
  } catch (e) { document.getElementById('adspamContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveAdSpamConfig() {
  try {
    const res = await api('/api/settings/ad-spam', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('adsEnable').checked, sensitivity: parseInt(document.getElementById('adsSens').value) }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadAdSpamConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadMessageLocksConfig() {
  try {
    const d = await api('/api/settings/message-locks'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('messagelocksContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>消息锁</h3>
      <div class="toggle-row"><span>禁止媒体消息</span><label class="toggle-switch"><input type="checkbox" id="mlMedia" ${cfg.media?'checked':''}><span class="slider"></span></label></div>
      <div class="toggle-row"><span>禁止贴纸</span><label class="toggle-switch"><input type="checkbox" id="mlSticker" ${cfg.sticker?'checked':''}><span class="slider"></span></label></div>
      <div class="toggle-row"><span>禁止投票</span><label class="toggle-switch"><input type="checkbox" id="mlPoll" ${cfg.poll?'checked':''}><span class="slider"></span></label></div>
      <div class="toggle-row"><span>禁止链接</span><label class="toggle-switch"><input type="checkbox" id="mlLink" ${cfg.link?'checked':''}><span class="slider"></span></label></div>
      <button class="btn btn-primary" onclick="saveMessageLocksConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('messagelocksContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveMessageLocksConfig() {
  try {
    const res = await api('/api/settings/message-locks', { method: 'POST', body: JSON.stringify({ media: document.getElementById('mlMedia').checked, sticker: document.getElementById('mlSticker').checked, poll: document.getElementById('mlPoll').checked, link: document.getElementById('mlLink').checked }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadMessageLocksConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadInactiveCleanConfig() {
  try {
    const d = await api('/api/settings/inactive-clean'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('inactivecleanContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>不活跃清理</h3>
      <div class="toggle-row"><span>启用清理</span><label class="toggle-switch"><input type="checkbox" id="icEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="form-group"><label>不活跃天数</label><input type="number" id="icDays" value="${cfg.days || 30}" min="1" class="input-field"></div>
      <button class="btn btn-primary" onclick="saveInactiveCleanConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('inactivecleanContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveInactiveCleanConfig() {
  try {
    const res = await api('/api/settings/inactive-clean', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('icEnable').checked, days: parseInt(document.getElementById('icDays').value) }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadInactiveCleanConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadGreetingConfig() {
  try {
    const d = await api('/api/settings/greeting'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('greetingContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>问候配置</h3>
      <div class="form-group"><label>说明</label><div class="hint-text">这里只保留真实生效的开关和时间，不再展示未接线的自定义文案字段。</div></div>
      <div class="toggle-row"><span>早安播报</span><label class="toggle-switch"><input type="checkbox" id="grMorningEn" ${cfg.morning_enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="form-group"><label>早安时间</label><input type="time" id="grMorningTime" value="${cfg.morning_time || '08:05'}" class="input-field"></div>
      <div class="toggle-row"><span>午安播报</span><label class="toggle-switch"><input type="checkbox" id="grAfternoonEn" ${cfg.afternoon_enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="form-group"><label>午安时间</label><input type="time" id="grAfternoonTime" value="${cfg.afternoon_time || '12:35'}" class="input-field"></div>
      <div class="toggle-row"><span>晚安播报</span><label class="toggle-switch"><input type="checkbox" id="grNightEn" ${cfg.evening_enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="form-group"><label>晚安时间</label><input type="time" id="grNightTime" value="${cfg.evening_time || '23:05'}" class="input-field"></div>
      <div class="toggle-row"><span>深夜问候</span><label class="toggle-switch"><input type="checkbox" id="grMidnightEn" ${cfg.night_enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="form-group"><label>深夜问候时间</label><input type="time" id="grMidnightTime" value="${cfg.night_time || '22:30'}" class="input-field"></div>
      <div class="toggle-row"><span>问候使用图片卡</span><label class="toggle-switch"><input type="checkbox" id="grImgCardEn" ${cfg.image_card_enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="toggle-row"><span>全局图片卡总开关</span><label class="toggle-switch"><input type="checkbox" id="grGlobalImgCardEn" ${cfg.broadcast_image_card_enabled?'checked':''}><span class="slider"></span></label></div>
      <button class="btn btn-primary" onclick="saveGreetingConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('greetingContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveGreetingConfig() {
  try {
    const res = await api('/api/settings/greeting', { method: 'POST', body: JSON.stringify({ morning_enabled: document.getElementById('grMorningEn').checked, morning_time: document.getElementById('grMorningTime').value, afternoon_enabled: document.getElementById('grAfternoonEn').checked, afternoon_time: document.getElementById('grAfternoonTime').value, evening_enabled: document.getElementById('grNightEn').checked, evening_time: document.getElementById('grNightTime').value, night_enabled: document.getElementById('grMidnightEn').checked, night_time: document.getElementById('grMidnightTime').value, image_card_enabled: document.getElementById('grImgCardEn').checked, broadcast_image_card_enabled: document.getElementById('grGlobalImgCardEn').checked }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadGreetingConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadMysticConfig() {
  try {
    const d = await api('/api/settings/mystic'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('mysticContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>三个时段，三种固定栏目</h3>
      <div class="toggle-row"><span>启用三档栏目</span><label class="toggle-switch"><input type="checkbox" id="mysticEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="toggle-row"><span>启用单按钮引导（每天三档轮换联系 Mory、预览福利、自助订阅）</span><label class="toggle-switch"><input type="checkbox" id="mysticCtaEnable" ${cfg.cta_enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="toggle-row"><span>启用私聊本地占卜（风水、塔罗、算卦请求自动回复，不调用 LLM）</span><label class="toggle-switch"><input type="checkbox" id="mysticPrivateReplyEnable" ${cfg.private_reply_enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="toggle-row"><span>传统文化播报使用图片卡</span><label class="toggle-switch"><input type="checkbox" id="mysticImgCardEn" ${cfg.image_card_enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="toggle-row"><span>全局图片卡总开关</span><label class="toggle-switch"><input type="checkbox" id="mysticGlobalImgCardEn" ${cfg.broadcast_image_card_enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="form-group"><label>📜 早间 · 今日黄历</label><div class="hint-text">真实农历、干支、宜忌、冲煞、值日、星宿、吉神方位、节气与彭祖百忌。</div><input type="time" id="mysticMorningTime" value="${cfg.morning_time || '09:05'}" class="input-field"></div>
      <div class="form-group"><label>🔮 午间 · 三张塔罗</label><div class="hint-text">每天无重复抽取主牌、助力、提醒，包含正逆位、元素与组合解读。</div><input type="time" id="mysticAfternoonTime" value="${cfg.afternoon_time || '13:05'}" class="input-field"></div>
      <div class="form-group"><label>☯️ 晚间 · 易经一卦</label><div class="hint-text">六十四卦中起本卦与动爻，计算真实之卦，并给出一个适合群聊延伸的观察问题。</div><input type="time" id="mysticEveningTime" value="${cfg.evening_time || '20:35'}" class="input-field"></div>
      <div class="form-group"><label>内容原则</label><div class="hint-text">三档身份固定、内容按日期高随机且同日重试一致；正文不做确定性断言。开启引导后每张卡最多一个与正文一致的按钮。</div></div>
      <button class="btn btn-primary" onclick="saveMysticConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('mysticContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveMysticConfig() {
  try {
    const res = await api('/api/settings/mystic', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('mysticEnable').checked, cta_enabled: document.getElementById('mysticCtaEnable').checked, private_reply_enabled: document.getElementById('mysticPrivateReplyEnable').checked, image_card_enabled: document.getElementById('mysticImgCardEn').checked, broadcast_image_card_enabled: document.getElementById('mysticGlobalImgCardEn').checked, morning_time: document.getElementById('mysticMorningTime').value, afternoon_time: document.getElementById('mysticAfternoonTime').value, evening_time: document.getElementById('mysticEveningTime').value }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadMysticConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadExchangeRateConfig() {
  try {
    const d = await api('/api/settings/exchange-rate'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('exchangerateContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>汇率配置</h3>
      <div class="toggle-row"><span>启用汇率查询</span><label class="toggle-switch"><input type="checkbox" id="erEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="form-group"><label>API密钥</label><input type="password" id="erApiKey" value="${cfg.api_key || ''}" class="input-field"></div>
      <button class="btn btn-primary" onclick="saveExchangeRateConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('exchangerateContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveExchangeRateConfig() {
  try {
    const res = await api('/api/settings/exchange-rate', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('erEnable').checked, api_key: document.getElementById('erApiKey').value }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadExchangeRateConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadVisualDashboardConfig() {
  try {
    const d = await api('/api/settings/dashboard'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('visualdashboardContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>可视化面板</h3>
      <div class="toggle-row"><span>启用可视化面板</span><label class="toggle-switch"><input type="checkbox" id="vdEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <button class="btn btn-primary" onclick="saveVisualDashboardConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('visualdashboardContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveVisualDashboardConfig() {
  try {
    const res = await api('/api/settings/dashboard', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('vdEnable').checked }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadVisualDashboardConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadLanguageConfig() {
  try {
    const d = await api('/api/settings/language'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('languageContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>语言设置</h3>
      <div class="form-group"><label>界面语言</label><select id="langSelect" class="input-field"><option value="zh" ${cfg.language==='zh'?'selected':''}>中文</option><option value="en" ${cfg.language==='en'?'selected':''}>English</option><option value="ja" ${cfg.language==='ja'?'selected':''}>日本語</option></select></div>
      <button class="btn btn-primary" onclick="saveLanguageConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('languageContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveLanguageConfig() {
  try {
    const res = await api('/api/settings/language', { method: 'POST', body: JSON.stringify({ language: document.getElementById('langSelect').value }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadLanguageConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadSpamActionConfig() {
  try {
    const d = await api('/api/settings/spam-action'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('spamactionContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>广告动作</h3>
      <div class="form-group"><label>处罚方式</label><select id="spamAction" class="input-field"><option value="mute" ${cfg.action==='mute'?'selected':''}>禁言</option><option value="ban" ${cfg.action==='ban'?'selected':''}>封禁</option><option value="delete" ${cfg.action==='delete'?'selected':''}>删除</option></select></div>
      <button class="btn btn-primary" onclick="saveSpamActionConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('spamactionContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveSpamActionConfig() {
  try {
    const res = await api('/api/settings/spam-action', { method: 'POST', body: JSON.stringify({ action: document.getElementById('spamAction').value }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadSpamActionConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadGoodbyeConfig() {
  try {
    const d = await api('/api/settings/goodbye'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('goodbyeContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>退群消息</h3>
      <div class="toggle-row"><span>启用退群消息</span><label class="toggle-switch"><input type="checkbox" id="gbEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="form-group"><label>退群消息文本</label><textarea id="gbText" class="input-field" rows="3">${cfg.text || ''}</textarea></div>
      <button class="btn btn-primary" onclick="saveGoodbyeConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('goodbyeContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveGoodbyeConfig() {
  try {
    const res = await api('/api/settings/goodbye', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('gbEnable').checked, text: document.getElementById('gbText').value }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadGoodbyeConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadRulesConfig() {
  try {
    const d = await api('/api/settings/rules'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('rulesContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>群规配置</h3>
      <div class="toggle-row"><span>启用群规</span><label class="toggle-switch"><input type="checkbox" id="rulesEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <div class="form-group"><label>群规内容</label><textarea id="rulesText" class="input-field" rows="6">${cfg.text || ''}</textarea></div>
      <button class="btn btn-primary" onclick="saveRulesConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('rulesContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveRulesConfig() {
  try {
    const res = await api('/api/settings/rules', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('rulesEnable').checked, text: document.getElementById('rulesText').value }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadRulesConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadGamesConfig() {
  try {
    const d = await api('/api/settings/games'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('gamesContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>游戏配置</h3>
      <div class="toggle-row"><span>启用小游戏</span><label class="toggle-switch"><input type="checkbox" id="gamesEnable" ${cfg.enabled?'checked':''}><span class="slider"></span></label></div>
      <button class="btn btn-primary" onclick="saveGamesConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('gamesContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveGamesConfig() {
  try {
    const res = await api('/api/settings/games', { method: 'POST', body: JSON.stringify({ enabled: document.getElementById('gamesEnable').checked }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadGamesConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadAiModelConfig() {
  try {
    const d = await api('/api/settings/ai-model'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('aimodelContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>AI模型参数</h3>
      <div class="form-group"><label>创意温度 (${cfg.temperature})</label><input type="range" id="aiTemp" value="${cfg.temperature}" min="0" max="2" step="0.05" class="input-field"><span id="aiTempVal">${cfg.temperature}</span></div>
      <div class="form-group"><label>Top-P采样 (${cfg.top_p})</label><input type="range" id="aiTopP" value="${cfg.top_p}" min="0" max="1" step="0.05" class="input-field"><span id="aiTopPVal">${cfg.top_p}</span></div>
      <div class="form-group"><label>最大Token数</label><input type="number" id="aiMaxTokens" value="${cfg.max_tokens}" min="100" max="4096" class="input-field"></div>
      <div class="form-group"><label>频率惩罚 (${cfg.frequency_penalty})</label><input type="range" id="aiFreqPen" value="${cfg.frequency_penalty}" min="-2" max="2" step="0.1" class="input-field"><span id="aiFreqPenVal">${cfg.frequency_penalty}</span></div>
      <div class="form-group"><label>存在惩罚 (${cfg.presence_penalty})</label><input type="range" id="aiPresPen" value="${cfg.presence_penalty}" min="-2" max="2" step="0.1" class="input-field"><span id="aiPresPenVal">${cfg.presence_penalty}</span></div>
      <div class="form-group"><label>群聊回复概率 (%)</label><input type="number" id="aiReplyChance" value="${cfg.reply_chance}" min="0" max="100" class="input-field"></div>
      <div class="form-group"><label>回复速度</label><select id="aiReplySpeed" class="input-field"><option value="instant" ${cfg.reply_speed==='instant'?'selected':''}>即时</option><option value="human" ${cfg.reply_speed==='human'?'selected':''}>拟人</option><option value="slow" ${cfg.reply_speed==='slow'?'selected':''}>慢速</option></select></div>
      <div class="form-group"><label>贴纸回复概率 (%)</label><input type="number" id="aiStickerChance" value="${cfg.reply_sticker_chance}" min="0" max="100" class="input-field"></div>
      <button class="btn btn-primary" onclick="saveAiModelConfig()">保存设置</button></div>`;
    ['aiTemp','aiTopP','aiFreqPen','aiPresPen'].forEach(id => {
      document.getElementById(id).addEventListener('input', function(){ document.getElementById(id+'Val').textContent = this.value; });
    });
  } catch (e) { document.getElementById('aimodelContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveAiModelConfig() {
  try {
    const res = await api('/api/settings/ai-model', { method: 'POST', body: JSON.stringify({
      temperature: parseFloat(document.getElementById('aiTemp').value),
      top_p: parseFloat(document.getElementById('aiTopP').value),
      max_tokens: parseInt(document.getElementById('aiMaxTokens').value),
      frequency_penalty: parseFloat(document.getElementById('aiFreqPen').value),
      presence_penalty: parseFloat(document.getElementById('aiPresPen').value),
      reply_chance: parseInt(document.getElementById('aiReplyChance').value),
      reply_speed: document.getElementById('aiReplySpeed').value,
      reply_sticker_chance: parseInt(document.getElementById('aiStickerChance').value),
    }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadAiModelConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadBotCoreConfig() {
  try {
    const d = await api('/api/settings/bot-core'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('botcoreContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>Bot核心配置</h3>
      <div class="form-group"><label>Bot名称</label><input type="text" id="bcName" value="${cfg.bot_name}" class="input-field"></div>
      <div class="form-group"><label>每小时请求限制</label><input type="number" id="bcMaxReq" value="${cfg.max_requests_per_user}" min="10" max="1000" class="input-field"></div>
      <div class="toggle-row"><span>允许删除消息</span><label class="toggle-switch"><input type="checkbox" id="bcMsgDel" ${cfg.enable_message_deletion?'checked':''}><span class="slider"></span></label></div>
      <button class="btn btn-primary" onclick="saveBotCoreConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('botcoreContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function saveBotCoreConfig() {
  try {
    const res = await api('/api/settings/bot-core', { method: 'POST', body: JSON.stringify({
      bot_name: document.getElementById('bcName').value,
      max_requests_per_user: parseInt(document.getElementById('bcMaxReq').value),
      enable_message_deletion: document.getElementById('bcMsgDel').checked,
    }) });
    if (res.ok) { showToast('✅ 配置已保存', 'success'); loadBotCoreConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadPricingConfig() {
  try {
    const d = await api('/api/settings/pricing'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('pricingContent'); if (!el) return;
    const items = cfg.price_list || {};
    let rows = '';
    for (const [key, val] of Object.entries(items)) {
      rows += `<tr>
        <td><input type="text" class="input-field price-name" data-key="${key}" value="${key}" style="width:120px"></td>
        <td><input type="number" class="input-field price-val" data-key="${key}" value="${typeof val === 'object' ? (val.price || 0) : val}" style="width:100px"></td>
        <td><button class="btn btn-sm btn-danger" onclick="deletePriceItem('${key}')">删除</button></td>
      </tr>`;
    }
    el.innerHTML = `<div class="card"><h3>定价管理</h3>
      <div class="table-wrapper"><table><thead><tr><th>商品名称</th><th>价格</th><th>操作</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div style="margin-top:12px;display:flex;gap:8px;">
        <input type="text" id="newPriceName" placeholder="新商品名" class="input-field" style="width:120px">
        <input type="number" id="newPriceVal" placeholder="价格" class="input-field" style="width:100px">
        <button class="btn btn-sm btn-secondary" onclick="addPriceItem()">添加</button>
      </div>
      <button class="btn btn-primary" style="margin-top:12px" onclick="savePricingConfig()">保存全部</button></div>`;
  } catch (e) { document.getElementById('pricingContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
function deletePriceItem(key) {
  const row = document.querySelector(`input.price-name[data-key="${key}"]`).closest('tr');
  row.remove();
}
function addPriceItem() {
  const name = document.getElementById('newPriceName').value.trim();
  const val = document.getElementById('newPriceVal').value.trim();
  if (!name || !val) { showToast('请填写名称和价格', 'error'); return; }
  const tbody = document.querySelector('#pricingContent table tbody');
  const row = document.createElement('tr');
  row.innerHTML = `<td><input type="text" class="input-field price-name" data-key="${name}" value="${name}" style="width:120px"></td><td><input type="number" class="input-field price-val" data-key="${name}" value="${val}" style="width:100px"></td><td><button class="btn btn-sm btn-danger" onclick="this.closest('tr').remove()">删除</button></td>`;
  tbody.appendChild(row);
  document.getElementById('newPriceName').value = '';
  document.getElementById('newPriceVal').value = '';
}
async function savePricingConfig() {
  try {
    const items = {};
    document.querySelectorAll('input.price-name').forEach(el => {
      const key = el.value.trim();
      const valEl = document.querySelector(`input.price-val[data-key="${el.dataset.key}"]`);
      if (key && valEl) items[key] = parseInt(valEl.value) || 0;
    });
    const res = await api('/api/settings/pricing', { method: 'POST', body: JSON.stringify({ price_list: items }) });
    if (res.ok) { showToast('✅ 定价已保存', 'success'); loadPricingConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

async function loadPersonaConfig() {
  try {
    const d = await api('/api/settings/persona'); if (!d.ok) return;
    const cfg = d.data; const el = document.getElementById('personaContent'); if (!el) return;
    el.innerHTML = `<div class="card"><h3>人设与提示词</h3>
      <div class="form-group"><label>系统提示词 <small>(${cfg.system_prompt.length}字符)</small></label><textarea id="perSysPrompt" class="input-field" rows="4">${cfg.system_prompt.replace(/`/g, '\\`').replace(/\\$/g, '\\$')}</textarea></div>
      <div class="form-group"><label>知识库 <small>(${cfg.knowledge.length}字符)</small></label><textarea id="perKnowledge" class="input-field" rows="4">${cfg.knowledge.replace(/`/g, '\\`').replace(/\\$/g, '\\$')}</textarea></div>
      <div class="form-group"><label>基础人设 <small>(${cfg.base_persona.length}字符)</small></label><textarea id="perBasePersona" class="input-field" rows="3">${cfg.base_persona.replace(/`/g, '\\`').replace(/\\$/g, '\\$')}</textarea></div>
      <div class="form-group"><label>风格追加 <small>(${cfg.style_append.length}字符)</small></label><textarea id="perStyleAppend" class="input-field" rows="2">${cfg.style_append.replace(/`/g, '\\`').replace(/\\$/g, '\\$')}</textarea></div>
      <div class="form-group"><label>附加知识 <small>(${cfg.added_knowledge.length}字符)</small></label><textarea id="perAddedKnowledge" class="input-field" rows="2">${cfg.added_knowledge.replace(/`/g, '\\`').replace(/\\$/g, '\\$')}</textarea></div>
      <button class="btn btn-primary" onclick="savePersonaConfig()">保存设置</button></div>`;
  } catch (e) { document.getElementById('personaContent').innerHTML = `<div class="error">加载失败: ${e.message}</div>`; }
}
async function savePersonaConfig() {
  try {
    const res = await api('/api/settings/persona', { method: 'POST', body: JSON.stringify({
      system_prompt: document.getElementById('perSysPrompt').value,
      knowledge: document.getElementById('perKnowledge').value,
      base_persona: document.getElementById('perBasePersona').value,
      style_append: document.getElementById('perStyleAppend').value,
      added_knowledge: document.getElementById('perAddedKnowledge').value,
    }) });
    if (res.ok) { showToast('✅ 人设已保存', 'success'); loadPersonaConfig(); } else { showToast('❌ ' + (res.msg || '保存失败'), 'error'); }
  } catch (e) { showToast('❌ 保存失败: ' + e.message, 'error'); }
}

// ============ 风格样本审核（Agent G）============
let _styleScene = '';
let _styleStatus = '';
const _sceneLabels = { chat: '聊天', greeting: '问候', engage: '搭讪', faq: 'FAQ', broadcast: '播报' };

async function loadReplyStyleSamples() {
  try {
    const qs = new URLSearchParams({ limit: '100' });
    if (_styleScene) qs.set('scene', _styleScene);
    if (_styleStatus) qs.set('status', _styleStatus);
    const d = await api(`/api/quality/reply-style-samples?${qs.toString()}`);
    const tb = document.getElementById('styleSampleBody');
    if (!tb) return;
    const rows = d.data || [];
    if (!rows.length) {
      tb.innerHTML = '<tr><td colspan="7" class="empty-state"><h3>暂无风格样本</h3></td></tr>';
      return;
    }
    tb.innerHTML = rows.map(s => `
      <tr>
        <td>${s.id}</td>
        <td>${escHtml(s.label || '')}</td>
        <td style="max-width:360px;word-break:break-all;">${escHtml(s.style_text || '')}</td>
        <td><span class="badge ${s.status === 'approved' ? 'badge-success' : s.status === 'rejected' ? 'badge-danger' : 'badge-warning'}">${s.status}</span></td>
        <td>${s.enabled ? '✅' : '—'}</td>
        <td>${escHtml(s.created_by || '')}</td>
        <td style="white-space:nowrap;">
          ${s.status === 'pending' ? `<button class="btn btn-sm btn-success" onclick="reviewStyleSample(${s.id},'approved',true)">通过+启用</button>
          <button class="btn btn-sm btn-secondary" onclick="reviewStyleSample(${s.id},'approved',false)">仅通过</button>
          <button class="btn btn-sm btn-danger" onclick="reviewStyleSample(${s.id},'rejected',false)">拒绝</button>` : ''}
          ${s.status === 'approved' ? `<button class="btn btn-sm btn-secondary" onclick="toggleStyleSample(${s.id}, ${s.enabled ? 'false' : 'true'})">${s.enabled ? '停用' : '启用'}</button>` : ''}
        </td>
      </tr>
    `).join('');
  } catch (e) { console.error(e); }
}

async function reviewStyleSample(id, status, enabled) {
  try {
    await api(`/api/quality/reply-style-samples/${id}/review`, {
      method: 'POST', body: JSON.stringify({ status, enabled })
    });
    showToast('✅ 审核完成', 'success');
    loadReplyStyleSamples();
  } catch (e) { showToast(e.message, 'error'); }
}

async function toggleStyleSample(id, enabled) {
  try {
    await api(`/api/quality/reply-style-samples/${id}/enabled`, {
      method: 'POST', body: JSON.stringify({ enabled })
    });
    showToast(enabled ? '✅ 已启用' : '✅ 已停用', 'success');
    loadReplyStyleSamples();
  } catch (e) { showToast(e.message, 'error'); }
}

function setStyleScene(scene) {
  _styleScene = scene;
  loadReplyStyleSamples();
}

function setStyleStatus(status) {
  _styleStatus = status;
  loadReplyStyleSamples();
}

// ============ 转化漏斗可视化（v5.26.0）============
let _funnelChart = null;
let _funnelTrendChart = null;

async function loadFunnelPage() {
  const daysEl = document.getElementById('funnelDays');
  const days = daysEl ? daysEl.value : '7';

  try {
    const [funnelData, trendData] = await Promise.all([
      api(`/api/analytics/funnel?days=${days}`),
      api(`/api/analytics/funnel/trend?days=${days}`)
    ]);

    renderFunnelStages(funnelData.data.stages);
    renderFunnelChart(funnelData.data.stages);
    renderFunnelTrendChart(trendData.data);
  } catch (e) {
    const el = document.getElementById('funnelStages');
    if (el) el.innerHTML = `<div class="card" style="grid-column: 1/-1;"><p style="color:#ef4444;">加载失败: ${escHtml(e.message)}</p></div>`;
  }
}

function renderFunnelStages(stages) {
  const el = document.getElementById('funnelStages');
  if (!el) return;

  const colors = ['#60a5fa', '#a78bfa', '#f59e0b', '#10b981'];
  const icons = ['👆', '💡', '🛒', '✅'];

  el.innerHTML = stages.map((stage, i) => `
    <div class="stat-card" style="border-left: 4px solid ${colors[i]};">
      <div class="stat-icon" style="background: ${colors[i]}22; color: ${colors[i]};">${icons[i]}</div>
      <div class="stat-value" style="color: ${colors[i]};">${stage.count}</div>
      <div class="stat-label">${stage.label}</div>
      <div style="margin-top: 8px; font-size: 13px; color: #94a3b8;">
        转化率: <span style="color: ${colors[i]}; font-weight: 600;">${stage.rate}%</span>
      </div>
    </div>
  `).join('');
}

function renderFunnelChart(stages) {
  const ctx = document.getElementById('funnelPageChart');
  if (!ctx) return;

  if (_funnelChart) {
    _funnelChart.destroy();
  }

  const colors = ['#60a5fa', '#a78bfa', '#f59e0b', '#10b981'];
  const labels = stages.map(s => s.label);
  const values = stages.map(s => s.count);

  _funnelChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: '用户数',
        data: values,
        backgroundColor: colors.map(c => c + 'cc'),
        borderColor: colors,
        borderWidth: 2,
        borderRadius: 8
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function(context) {
              const stage = stages[context.dataIndex];
              return `数量: ${stage.count}, 转化率: ${stage.rate}%`;
            }
          }
        }
      },
      scales: {
        x: {
          ticks: { color: '#6b7280' },
          grid: { color: 'rgba(255,255,255,0.05)' }
        },
        y: {
          ticks: { color: '#e2e8f0', font: { size: 13, weight: '600' } },
          grid: { display: false }
        }
      }
    }
  });
}

function renderFunnelTrendChart(data) {
  const ctx = document.getElementById('funnelTrendChart');
  if (!ctx) return;

  if (_funnelTrendChart) {
    _funnelTrendChart.destroy();
  }

  const colors = ['#60a5fa', '#a78bfa', '#f59e0b', '#10b981'];
  const stageNames = ['接触', '感兴趣', '加购', '转化'];
  const stageKeys = ['touched', 'interested', 'carted', 'converted'];

  const datasets = stageKeys.map((key, i) => ({
    label: stageNames[i],
    data: data.series[key] || [],
    borderColor: colors[i],
    backgroundColor: colors[i] + '22',
    tension: 0.4,
    fill: false,
    pointRadius: 4,
    pointHoverRadius: 6
  }));

  _funnelTrendChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: data.dates || [],
      datasets: datasets
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          labels: { color: '#e2e8f0' }
        },
        tooltip: {
          mode: 'index',
          intersect: false
        }
      },
      scales: {
        x: {
          ticks: { color: '#6b7280', maxTicksLimit: 10 },
          grid: { display: false }
        },
        y: {
          ticks: { color: '#6b7280' },
          grid: { color: 'rgba(255,255,255,0.05)' }
        }
      }
    }
  });
}

// ============ 转化归因分析（v5.24.0 阶段3-C）============
let _attrTab = 'campaign';
function switchAttrTab(tab) {
  _attrTab = tab;
  document.querySelectorAll('.attr-tab-btn').forEach(b => {
    const active = b.dataset.tab === tab;
    b.style.background = active ? 'linear-gradient(135deg, #60a5fa, #3b82f6)' : 'rgba(255,255,255,0.05)';
    b.style.color = active ? 'white' : '#e2e8f0';
    b.style.border = active ? 'none' : '1px solid rgba(255,255,255,0.1)';
  });
  document.querySelectorAll('.attr-section').forEach(s => s.style.display = 'none');
  const sec = document.getElementById('attrSection_' + tab);
  if (sec) sec.style.display = 'block';
}

async function loadAttributionReport() {
  const el = document.getElementById('attributionContent');
  if (!el) return;
  el.innerHTML = '<div class="loading">加载中...</div>';
  try {
    const [camp, hour, pers, mem, growth] = await Promise.all([
      api('/api/attribution/by-campaign?days=7'),
      api('/api/attribution/by-hour?days=7'),
      api('/api/attribution/by-persona?days=7'),
      api('/api/attribution/memory-impact?days=7'),
      api('/api/attribution/growth-summary?days=7')
    ]);
    const disabled = camp.disabled;
    const notice = disabled ? `<div class="card" style="margin-bottom:16px; border-left:4px solid #f59e0b;"><p style="color:#f59e0b; margin:0;">⚠️ 归因报表功能未开启（ATTRIBUTION_REPORT_ENABLED=false），数据为空。请在 config.json 中开启后刷新。</p></div>` : '';
    el.innerHTML = notice +
      `<div style="display:flex; gap:8px; margin-bottom:20px; flex-wrap:wrap;">
        <button class="btn btn-secondary attr-tab-btn" data-tab="campaign" onclick="switchAttrTab('campaign')">📊 Campaign 维度</button>
        <button class="btn btn-secondary attr-tab-btn" data-tab="hour" onclick="switchAttrTab('hour')">🕐 时段维度</button>
        <button class="btn btn-secondary attr-tab-btn" data-tab="persona" onclick="switchAttrTab('persona')">💬 人设桶维度</button>
        <button class="btn btn-secondary attr-tab-btn" data-tab="memory" onclick="switchAttrTab('memory')">🧠 记忆系统贡献</button>
        <button class="btn btn-secondary attr-tab-btn" data-tab="growth" onclick="switchAttrTab('growth')">增长优化</button>
      </div>` +
      `<div id="attrSection_campaign" class="attr-section">${renderAttrCampaign(camp.data)}</div>` +
      `<div id="attrSection_hour" class="attr-section" style="display:none;">${renderAttrHour(hour.data)}</div>` +
      `<div id="attrSection_persona" class="attr-section" style="display:none;">${renderAttrPersona(pers.data)}</div>` +
      `<div id="attrSection_memory" class="attr-section" style="display:none;">${renderAttrMemory(mem.data)}</div>` +
      `<div id="attrSection_growth" class="attr-section" style="display:none;">${renderAttrGrowth(growth.data)}</div>`;
    switchAttrTab(_attrTab);
  } catch (e) {
    el.innerHTML = `<div class="error">加载失败: ${escHtml(e.message)}</div>`;
  }
}

function renderAttrGrowth(data) {
  if (!data || data.length === 0) return '<div class="card"><p style="color:#6b7280;">暂无增长优化数据</p></div>';
  const rows = data.map(d => {
    const events = d.events || {};
    const telemetry = d.telemetry || {};
    return `<tr>
      <td style="font-family:'JetBrains Mono',monospace; color:#60a5fa;">${escHtml(d.experiment_id)}</td>
      <td>${escHtml(d.name)}</td>
      <td>${events.touched || 0}</td>
      <td>${events.interested || 0}</td>
      <td>${events.consulted || 0}</td>
      <td>${events.carted || 0}</td>
      <td>${events.converted || events.paid || 0}</td>
      <td>${telemetry.engage || 0}</td>
    </tr>`;
  }).join('');
  return `<div class="card">
    <h3 style="color:#fff; margin-bottom:16px;">10 项增长优化汇总</h3>
    <p style="color:#94a3b8; margin-bottom:16px; font-size:13px;">数据来自 conversion_events 和 telemetry_events。刚上线时样本少，先看是否有事件进入链路，后续再看转化率。</p>
    <table class="data-table">
      <thead><tr><th>实验ID</th><th>方向</th><th>触达</th><th>兴趣</th><th>咨询</th><th>加购</th><th>成交</th><th>互动</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

function renderAttrCampaign(data) {
  if (!data || data.length === 0) return '<div class="card"><p style="color:#6b7280;">暂无 Campaign 归因数据</p></div>';
  const maxConv = Math.max(...data.map(d => d.conversions), 1);
  const rows = data.map(d => {
    const barW = (d.conversions / maxConv * 100).toFixed(1);
    return `<tr>
      <td style="font-family:'JetBrains Mono',monospace; color:#60a5fa;">${escHtml(d.campaign_id)}</td>
      <td>${escHtml(d.campaign_name)}</td>
      <td>${d.clicks}</td>
      <td>${d.carts}</td>
      <td><span style="color:#10b981; font-weight:600;">${d.conversions}</span></td>
      <td style="min-width:160px;">
        <div style="display:flex; align-items:center; gap:8px;">
          <div style="flex:1; height:8px; background:rgba(255,255,255,0.05); border-radius:4px; overflow:hidden;">
            <div style="width:${barW}%; height:100%; background:linear-gradient(90deg,#10b981,#34d399);"></div>
          </div>
          <span style="color:#10b981; font-size:12px; min-width:50px;">${d.cr}%</span>
        </div>
      </td>
    </tr>`;
  }).join('');
  return `<div class="card">
    <h3 style="color:#fff; margin-bottom:16px;">📊 Campaign 维度归因（按转化数排序）</h3>
    <table class="data-table">
      <thead><tr><th>Campaign ID</th><th>名称</th><th>点击</th><th>加购</th><th>转化</th><th>转化率 CR</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

function renderAttrHour(data) {
  // 补全 24 小时
  const hourMap = {};
  (data || []).forEach(d => { hourMap[d.hour] = d; });
  const hours = [];
  for (let h = 0; h < 24; h++) {
    hours.push(hourMap[h] || { hour: h, conversions: 0, total_events: 0 });
  }
  const maxConv = Math.max(...hours.map(h => h.conversions), 1);
  // 纯 CSS 柱状图模拟 24 小时折线趋势
  const bars = hours.map(h => {
    const barH = Math.max(h.conversions / maxConv * 100, 2);
    return `<div style="flex:1; display:flex; flex-direction:column; align-items:center; gap:4px; min-width:0;">
      <span style="color:#e2e8f0; font-size:10px;">${h.conversions || ''}</span>
      <div style="width:80%; height:${barH}px; background:linear-gradient(180deg,#60a5fa,#3b82f6); border-radius:3px 3px 0 0; min-height:2px;" title="${h.hour}时 转化${h.conversions} 事件${h.total_events}"></div>
      <span style="color:#6b7280; font-size:10px;">${h.hour}</span>
    </div>`;
  }).join('');
  const rows = hours.map(h => `<tr><td>${h.hour}:00 - ${h.hour}:59</td><td>${h.conversions}</td><td>${h.total_events}</td></tr>`).join('');
  return `<div class="card">
    <h3 style="color:#fff; margin-bottom:16px;">🕐 24 小时时段分布（转化数趋势）</h3>
    <div style="display:flex; align-items:flex-end; gap:4px; height:140px; padding:0 8px; margin-bottom:20px;">
      ${bars}
    </div>
    <table class="data-table">
      <thead><tr><th>时段</th><th>转化数</th><th>总事件数</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

function renderAttrPersona(data) {
  if (!data || data.length === 0) return '<div class="card"><p style="color:#6b7280;">暂无人设桶归因数据</p></div>';
  const bucketNames = { cold: '清冷', savage: '毒舌', soft: '撒娇', common: '通用' };
  const bucketColors = { cold: '#60a5fa', savage: '#ef4444', soft: '#ec4899', common: '#a78bfa' };
  const maxTotal = Math.max(...data.map(d => d.total_count), 1);
  const rows = data.map(d => {
    const barW = (d.total_count / maxTotal * 100).toFixed(1);
    const color = bucketColors[d.persona_bucket] || '#94a3b8';
    const name = bucketNames[d.persona_bucket] || d.persona_bucket;
    return `<tr>
      <td><span class="badge" style="background:${color}22; color:${color};">${escHtml(d.persona_bucket)}</span></td>
      <td>${escHtml(name)}</td>
      <td>${d.interested_count}</td>
      <td>${d.total_count}</td>
      <td style="min-width:160px;">
        <div style="display:flex; align-items:center; gap:8px;">
          <div style="flex:1; height:8px; background:rgba(255,255,255,0.05); border-radius:4px; overflow:hidden;">
            <div style="width:${barW}%; height:100%; background:${color};"></div>
          </div>
          <span style="color:${color}; font-size:12px; min-width:50px;">${d.conversion_rate}%</span>
        </div>
      </td>
    </tr>`;
  }).join('');
  return `<div class="card">
    <h3 style="color:#fff; margin-bottom:16px;">💬 人设桶维度归因</h3>
    <table class="data-table">
      <thead><tr><th>人设桶</th><th>中文名</th><th>兴趣数</th><th>总数</th><th>转化率</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

function renderAttrMemory(data) {
  if (!data || !data.memory_assisted) return '<div class="card"><p style="color:#6b7280;">暂无记忆系统归因数据</p></div>';
  const ma = data.memory_assisted;
  const na = data.non_assisted;
  const lift = data.lift_ratio;
  const days = data.days || 7;
  // 对比柱状图：有记忆 vs 无记忆的转化率（归一化到最大值）
  const maxRate = Math.max(ma.carted_rate, ma.converted_rate, na.carted_rate, na.converted_rate, 1);
  const barW = (rate) => (rate / maxRate * 100).toFixed(1);
  // 提升比率颜色：>1 绿色（提升），<1 红色（下降），=1 灰色
  const liftColor = (v) => v > 1 ? '#10b981' : (v < 1 && v > 0 ? '#ef4444' : '#94a3b8');
  const liftLabel = (v) => v > 1 ? `↑ ${v}x 提升` : (v < 1 && v > 0 ? `↓ ${v}x 下降` : '— 无对比');
  return `<div class="card">
    <h3 style="color:#fff; margin-bottom:16px;">🧠 记忆系统转化贡献（最近 ${days} 天）</h3>
    <p style="color:#94a3b8; margin-bottom:20px; font-size:13px;">对比有记忆辅助（memory_summary 注入）vs 无记忆辅助的会话转化率，量化记忆系统 ROI</p>

    <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:24px;">
      <div style="background:rgba(96,165,250,0.08); border:1px solid rgba(96,165,250,0.2); border-radius:12px; padding:16px;">
        <h4 style="color:#60a5fa; margin:0 0 12px 0;">🧠 有记忆辅助</h4>
        <p style="color:#94a3b8; font-size:12px; margin:0 0 8px 0;">会话数: ${ma.count} | interested: ${ma.interested} | carted: ${ma.carted} | converted: ${ma.converted}</p>
        <div style="margin-bottom:8px;">
          <span style="color:#e2e8f0; font-size:13px;">加购转化率（interested→carted）</span>
          <div style="display:flex; align-items:center; gap:8px; margin-top:4px;">
            <div style="flex:1; height:10px; background:rgba(255,255,255,0.05); border-radius:5px; overflow:hidden;">
              <div style="width:${barW(ma.carted_rate)}%; height:100%; background:linear-gradient(90deg,#60a5fa,#3b82f6);"></div>
            </div>
            <span style="color:#60a5fa; font-weight:600; min-width:60px; text-align:right;">${ma.carted_rate}%</span>
          </div>
        </div>
        <div>
          <span style="color:#e2e8f0; font-size:13px;">成交转化率（carted→converted）</span>
          <div style="display:flex; align-items:center; gap:8px; margin-top:4px;">
            <div style="flex:1; height:10px; background:rgba(255,255,255,0.05); border-radius:5px; overflow:hidden;">
              <div style="width:${barW(ma.converted_rate)}%; height:100%; background:linear-gradient(90deg,#10b981,#34d399);"></div>
            </div>
            <span style="color:#10b981; font-weight:600; min-width:60px; text-align:right;">${ma.converted_rate}%</span>
          </div>
        </div>
      </div>

      <div style="background:rgba(148,163,184,0.08); border:1px solid rgba(148,163,184,0.2); border-radius:12px; padding:16px;">
        <h4 style="color:#94a3b8; margin:0 0 12px 0;">⚪ 无记忆辅助</h4>
        <p style="color:#94a3b8; font-size:12px; margin:0 0 8px 0;">会话数: ${na.count} | interested: ${na.interested} | carted: ${na.carted} | converted: ${na.converted}</p>
        <div style="margin-bottom:8px;">
          <span style="color:#e2e8f0; font-size:13px;">加购转化率（interested→carted）</span>
          <div style="display:flex; align-items:center; gap:8px; margin-top:4px;">
            <div style="flex:1; height:10px; background:rgba(255,255,255,0.05); border-radius:5px; overflow:hidden;">
              <div style="width:${barW(na.carted_rate)}%; height:100%; background:rgba(148,163,184,0.6);"></div>
            </div>
            <span style="color:#94a3b8; font-weight:600; min-width:60px; text-align:right;">${na.carted_rate}%</span>
          </div>
        </div>
        <div>
          <span style="color:#e2e8f0; font-size:13px;">成交转化率（carted→converted）</span>
          <div style="display:flex; align-items:center; gap:8px; margin-top:4px;">
            <div style="flex:1; height:10px; background:rgba(255,255,255,0.05); border-radius:5px; overflow:hidden;">
              <div style="width:${barW(na.converted_rate)}%; height:100%; background:rgba(148,163,184,0.6);"></div>
            </div>
            <span style="color:#94a3b8; font-weight:600; min-width:60px; text-align:right;">${na.converted_rate}%</span>
          </div>
        </div>
      </div>
    </div>

    <div style="background:rgba(16,185,129,0.05); border:1px solid rgba(16,185,129,0.2); border-radius:12px; padding:16px;">
      <h4 style="color:#fff; margin:0 0 12px 0;">📈 提升比率（lift ratio = 有记忆 / 无记忆）</h4>
      <div style="display:flex; gap:24px; flex-wrap:wrap;">
        <div>
          <span style="color:#94a3b8; font-size:13px;">加购转化提升</span>
          <div style="margin-top:4px;">
            <span style="font-size:24px; font-weight:700; color:${liftColor(lift.carted)};">${lift.carted}x</span>
            <span style="color:${liftColor(lift.carted)}; font-size:13px; margin-left:8px;">${liftLabel(lift.carted)}</span>
          </div>
        </div>
        <div>
          <span style="color:#94a3b8; font-size:13px;">成交转化提升</span>
          <div style="margin-top:4px;">
            <span style="font-size:24px; font-weight:700; color:${liftColor(lift.converted)};">${lift.converted}x</span>
            <span style="color:${liftColor(lift.converted)}; font-size:13px; margin-left:8px;">${liftLabel(lift.converted)}</span>
          </div>
        </div>
      </div>
      <p style="color:#6b7280; font-size:11px; margin:12px 0 0 0;">注：lift > 1 表示记忆系统正向贡献，< 1 表示负向，= 0 表示无对比数据（分母为 0）</p>
    </div>
  </div>`;
}

// ============ 大模型效能对比（阶段2-C 多模型路由 A/B 测试）============
let _modelPerfChart1 = null;  // 转化率柱状图
let _modelPerfChart2 = null;  // 延迟折线图

async function loadModelPerfReport() {
  const el = document.getElementById('modelPerfContent');
  if (!el) return;
  el.innerHTML = '<div class="loading">加载中...</div>';
  try {
    const res = await api('/api/ab-test/report?days=7');
    const disabled = res.disabled;
    const data = res.data || [];
    const notice = disabled ? `<div class="card" style="margin-bottom:16px; border-left:4px solid #f59e0b;"><p style="color:#f59e0b; margin:0;">⚠️ A/B 测试未开启（AB_TEST_ENABLED=false），数据为空。请在 config.json 中开启后刷新。</p></div>` : '';
    if (!disabled && data.length === 0) {
      el.innerHTML = notice + '<div class="card"><p style="color:#6b7280;">暂无 A/B 测试数据，开启 AB_TEST_ENABLED 并产生对话后刷新。</p></div>';
      return;
    }
    el.innerHTML = notice +
      `<div class="charts-grid">
        <div class="chart-card">
          <div class="chart-header"><span class="chart-title">📊 各组转化率对比（柱状图）</span></div>
          <div class="chart-container"><canvas id="modelPerfChart1"></canvas></div>
        </div>
        <div class="chart-card">
          <div class="chart-header"><span class="chart-title">⚡ 各组平均延迟对比（折线图）</span></div>
          <div class="chart-container"><canvas id="modelPerfChart2"></canvas></div>
        </div>
      </div>
      <div class="card" style="margin-top:16px;">
        <h3 style="color:#fff; margin-bottom:16px;">💰 各组平均成本与详细指标</h3>
        <div id="modelPerfTable">${renderModelPerfTable(data)}</div>
      </div>`;
    if (!disabled && data.length > 0) {
      renderModelPerfCharts(data);
    }
  } catch (e) {
    el.innerHTML = `<div class="error">加载失败: ${escHtml(e.message)}</div>`;
  }
}

function renderModelPerfTable(data) {
  if (!data || data.length === 0) return '<p style="color:#6b7280;">暂无数据</p>';
  const groupNames = { 'A': '对照组（A）', 'B': '实验组（B）', 'Base': '基线组（Base）' };
  const groupColors = { 'A': '#60a5fa', 'B': '#a78bfa', 'Base': '#10b981' };
  const rows = data.map(d => {
    const color = groupColors[d.group] || '#94a3b8';
    const name = groupNames[d.group] || d.group;
    return `<tr>
      <td><span class="badge" style="background:${color}22; color:${color};">${escHtml(d.group)}</span></td>
      <td>${escHtml(name)}</td>
      <td style="font-family:'JetBrains Mono',monospace; color:#60a5fa;">${escHtml(d.model)}</td>
      <td>${d.sample_count}</td>
      <td style="color:#60a5fa; font-weight:600;">${d.avg_latency} ms</td>
      <td style="color:#f59e0b;">${d.p95_latency} ms</td>
      <td style="color:#10b981; font-family:'JetBrains Mono',monospace;">¥${d.avg_cost.toFixed(6)}</td>
      <td style="color:#10b981; font-weight:600;">${d.conversion_rate}%</td>
    </tr>`;
  }).join('');
  return `<table class="data-table">
    <thead><tr><th>组别</th><th>组名</th><th>模型</th><th>样本数</th><th>平均延迟</th><th>P95延迟</th><th>平均成本</th><th>转化率</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function renderModelPerfCharts(data) {
  // 组别标签：组名（模型名）
  const labels = data.map(d => {
    const names = { 'A': '对照组', 'B': '实验组', 'Base': '基线组' };
    return `${names[d.group] || d.group}\\n${d.model}`;
  });
  const groupColors = { 'A': '#60a5fa', 'B': '#a78bfa', 'Base': '#10b981' };
  const barColors = data.map(d => groupColors[d.group] || '#94a3b8');

  // 柱状图：转化率
  const ctx1 = document.getElementById('modelPerfChart1');
  if (ctx1) {
    if (_modelPerfChart1) _modelPerfChart1.destroy();
    _modelPerfChart1 = new Chart(ctx1, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          label: '转化率 (%)',
          data: data.map(d => d.conversion_rate),
          backgroundColor: barColors.map(c => c + '88'),
          borderColor: barColors,
          borderWidth: 2,
          borderRadius: 6,
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: '#e2e8f0' } },
          tooltip: { callbacks: { label: (ctx) => `转化率: ${ctx.parsed.y}%` } }
        },
        scales: {
          x: { ticks: { color: '#94a3b8', font: { size: 11 } }, grid: { color: 'rgba(255,255,255,0.05)' } },
          y: { ticks: { color: '#94a3b8', callback: (v) => v + '%' }, grid: { color: 'rgba(255,255,255,0.05)' } }
        }
      }
    });
  }

  // 折线图：平均延迟
  const ctx2 = document.getElementById('modelPerfChart2');
  if (ctx2) {
    if (_modelPerfChart2) _modelPerfChart2.destroy();
    _modelPerfChart2 = new Chart(ctx2, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: '平均延迟 (ms)',
          data: data.map(d => d.avg_latency),
          borderColor: '#f59e0b',
          backgroundColor: 'rgba(245,158,11,0.15)',
          borderWidth: 2,
          tension: 0.3,
          fill: true,
          pointBackgroundColor: barColors,
          pointBorderColor: '#fff',
          pointRadius: 6,
        }, {
          label: 'P95延迟 (ms)',
          data: data.map(d => d.p95_latency),
          borderColor: '#ef4444',
          backgroundColor: 'rgba(239,68,68,0.1)',
          borderWidth: 2,
          tension: 0.3,
          fill: false,
          pointBackgroundColor: '#ef4444',
          pointRadius: 5,
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#e2e8f0' } } },
        scales: {
          x: { ticks: { color: '#94a3b8', font: { size: 11 } }, grid: { color: 'rgba(255,255,255,0.05)' } },
          y: { ticks: { color: '#94a3b8', callback: (v) => v + 'ms' }, grid: { color: 'rgba(255,255,255,0.05)' } }
        }
      }
    });
  }
}

document.addEventListener('DOMContentLoaded', init);
</script>
</body>
</html>
'''

LOGIN_PAGE = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mory Assistant - 登录</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
* { font-family: 'Inter', system-ui, sans-serif; box-sizing: border-box; }
body { margin: 0; padding: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center; background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 50%, #16213e 100%); }
.login-box { background: rgba(30, 30, 46, 0.95); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 24px; padding: 48px; width: 100%; max-width: 420px; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5); }
.login-icon { text-align: center; font-size: 48px; margin-bottom: 24px; }
.login-title { font-size: 28px; font-weight: 700; text-align: center; margin: 0 0 8px 0; background: linear-gradient(135deg, #60a5fa, #a78bfa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.login-subtitle { text-align: center; color: #94a3b8; margin: 0 0 8px 0; font-size: 14px; }
.login-desc { text-align: center; color: #64748b; margin: 0 0 32px 0; font-size: 12px; }
.input-group { margin-bottom: 20px; }
.input-group label { display: block; color: #94a3b8; font-size: 13px; font-weight: 500; margin-bottom: 8px; }
.input-field { width: 100%; padding: 14px 16px; background: #1e1e2e; border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 12px; color: #e2e8f0; font-size: 15px; transition: all 0.3s; }
.input-field:focus { outline: none; border-color: #60a5fa; box-shadow: 0 0 0 3px rgba(96, 165, 250, 0.2); }
.login-btn { width: 100%; padding: 14px; background: linear-gradient(135deg, #60a5fa, #3b82f6); border: none; border-radius: 12px; color: white; font-size: 15px; font-weight: 600; cursor: pointer; transition: all 0.3s; }
.login-btn:hover { transform: translateY(-2px); box-shadow: 0 10px 20px rgba(59, 130, 246, 0.3); }
</style>
</head>
<body>
<div class="login-container">
  <div class="login-box">
    <div class="login-icon">🤖</div>
    <h1 class="login-title">Mory Assistant</h1>
    <p class="login-subtitle">私域可视化面板 v6.0</p>
    <p class="login-desc">Telegram群管机器人管理后台 — 数据监控 · 配置管理 · 群管设置</p>
    <div class="input-group">
      <label>访问密码</label>
      <input type="password" id="password" class="input-field" placeholder="请输入访问密码" onkeyup="if(event.key === 'Enter') doLogin()">
    </div>
    <button class="login-btn" onclick="doLogin()">登录</button>
  </div>
</div>
<script>
async function doLogin() {
  const pw = document.getElementById('password').value;
  if (!pw) return;
  try {
    const res = await fetch('/api/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: JSON.stringify({ password: pw })
    });
    const d = await res.json();
    if (d.ok) {
      window.location.reload();
    } else {
      alert(d.msg || '登录失败');
    }
  } catch (e) {
      alert('登录失败: ' + (e.message || e));
    }
}
</script>
</body>
</html>
'''
