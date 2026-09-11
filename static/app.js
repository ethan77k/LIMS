/* 实验室信息管理系统 LIMS —— 前端 SPA（Vue3，无构建） */
const { createApp, reactive, computed, onMounted } = Vue;

/* ---------------- 全局状态 ---------------- */
const state = reactive({
  token: localStorage.getItem('lims_token') || '',
  role: localStorage.getItem('lims_role') || '',
  name: localStorage.getItem('lims_name') || '',
  route: '/dashboard',
  toast: { msg: '', type: '' },
  orderPrefill: null,
});

/* ---------------- 角色权限与默认首页 ---------------- */
const ROLE_ROUTES = {
  admin: ['/dashboard', '/orders/new', '/orders/query', '/review', '/samples', '/schedule', '/expstart', '/exptrack', '/expend', '/reports', '/equipment', '/boards', '/handover', '/statistics', '/customers', '/audit', '/users', '/cases'],
  experimenter: ['/dashboard', '/orders/query', '/review', '/samples', '/schedule', '/expstart', '/exptrack', '/expend', '/reports', '/boards', '/handover', '/statistics', '/customers', '/cases'],
  entruster: ['/orders/new', '/orders/query', '/cases'],
};
function homeRoute(role) { return role === 'entruster' ? '/orders/query' : '/dashboard'; }

/* ---------------- 工具函数 ---------------- */
async function api(path, method = 'GET', body = null) {
  const headers = {};
  if (state.token) headers['Authorization'] = 'Bearer ' + state.token;
  if (body !== null) headers['Content-Type'] = 'application/json';
  const res = await fetch(path, { method, headers, body: body !== null ? JSON.stringify(body) : null });
  const ct = res.headers.get('content-type') || '';
  const data = ct.includes('json') ? await res.json() : await res.text();
  if (res.status === 401) { logout(); throw new Error('未登录或登录已过期'); }
  if (!res.ok) throw new Error((data && data.detail) || (data && data.message) || '请求失败');
  return data;
}

function toast(msg, type = '') {
  state.toast.msg = msg; state.toast.type = type;
  setTimeout(() => { state.toast.msg = ''; }, 2500);
}

function logout() {
  state.token = ''; state.role = ''; state.name = '';
  localStorage.removeItem('lims_token'); localStorage.removeItem('lims_role'); localStorage.removeItem('lims_name');
  state.route = '/dashboard';
}

/* OnlyOffice 编辑器 JS 装载助手（懒加载一次，全局复用） */
function loadOO(ooUrl) {
  return new Promise((resolve) => {
    if (window.DocsAPI) return resolve(window.DocsAPI);
    let s = document.getElementById('onlyoffice-api');
    if (s) {
      const wait = () => { if (window.DocsAPI) resolve(window.DocsAPI); else setTimeout(wait, 120); };
      wait(); return;
    }
    s = document.createElement('script');
    s.id = 'onlyoffice-api';
    s.src = ooUrl.replace(/\/+$/, '') + '/web-apps/apps/api/documents/api.js';
    s.onload = () => resolve(window.DocsAPI);
    s.onerror = () => { s.remove(); resolve(null); };
    document.head.appendChild(s);
  });
}

function navigate(r) { location.hash = r; }

function fmtDT(v) { return v ? String(v).replace('T', ' ').slice(0, 16) : ''; }
function fmtD(v) { return v ? String(v).slice(0, 10) : ''; }
function fmtLocal(v) { return v ? String(v).slice(0, 16) : ''; }
function escHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

const ORDER_STATUS = {
  '待审核': 'gray', '已审核': 'blue', '已排期': 'purple', '实验中': 'orange', '已完成': 'green', '已否决': 'red',
};
const SAMPLE_STATUS = {
  '待接收': 'gray', '已接收': 'blue', '已排期': 'purple', '实验中': 'orange', '已完成': 'green',
  '已退还': 'gray', '已报废': 'red', '已留存': 'green',
};
function badge(status, map) { const c = (map || ORDER_STATUS)[status] || 'gray'; return `<span class="badge ${c}">${status}</span>`; }

/* ---------------- 登录页 ---------------- */
const LoginPage = {
  data: () => ({ username: '', password: '', error: '' }),
  methods: {
    async login() {
      try {
        const r = await api('/api/auth/login', 'POST', { username: this.username, password: this.password });
        state.token = r.access_token; state.role = r.role; state.name = r.name;
        localStorage.setItem('lims_token', r.access_token);
        localStorage.setItem('lims_role', r.role); localStorage.setItem('lims_name', r.name);
        location.hash = homeRoute(r.role);
        state.route = homeRoute(r.role);
        toast('登录成功', 'success');
      } catch (e) { this.error = e.message; }
    },
    goPublic() { state.route = '/orders/new'; },
  },
  template: `
  <div class="login-wrap">
    <div class="login-card">
      <h1>实验室信息管理系统</h1>
      <div class="sub">Laboratory Information Management System</div>
      <div class="form-group"><label>用户名</label><input v-model="username" @keyup.enter="login" placeholder="请输入用户名"></div>
      <div class="form-group"><label>密码</label><input type="password" v-model="password" @keyup.enter="login" placeholder="请输入密码"></div>
      <p v-if="error" style="color:#c62828;font-size:12px;margin-bottom:10px">{{error}}</p>
      <button class="btn primary" style="width:100%" @click="login">登 录</button>
      <button class="btn link" style="width:100%;margin-top:12px" @click="goPublic">免登录填写委托申请 →</button>
    </div>
  </div>`,
};

/* ---------------- 公共页（免登录） ---------------- */
const PublicPage = {
  data: () => ({ route: '' }),
  computed: {
    view() { return this.route; },
  },
  methods: { navigate, toLogin() { state.route = '/login'; } },
  created() { this.route = state.route; },
  template: `
  <div>
    <div class="topbar">
      <div class="title">实验室信息管理系统</div>
      <div class="user">
        <a class="btn link" @click="navigate('/orders/new')">委托申请</a>
        <a class="btn link" @click="navigate('/orders/query')">委托查询</a>
        <button class="btn primary sm" @click="toLogin">登录</button>
      </div>
    </div>
    <div class="content">
      <order-new v-if="state.route === '/orders/new'"></order-new>
      <order-query v-else-if="state.route === '/orders/query'"></order-query>
      <div v-else>请选择功能</div>
    </div>
  </div>`,
};

/* ---------------- 主布局 ---------------- */
const MainLayout = {
  computed: {
    nav() {
      const menus = {
        admin: [
          { group: '工作台', links: [{ r: '/dashboard', t: '工作台' }] },
          { group: '委托管理', links: [
            { r: '/orders/new', t: '委托申请' }, { r: '/orders/query', t: '委托查询' }, { r: '/review', t: '委托审核' }, { r: '/cases', t: '测试用例库' }] },
          { group: '实验管理', links: [
            { r: '/samples', t: '样品管理' }, { r: '/schedule', t: '实验排期' }, { r: '/expstart', t: '实验开始' }, { r: '/exptrack', t: '实验跟踪' }, { r: '/expend', t: '实验结束' }] },
          { group: '报告', links: [{ r: '/reports', t: '实验报告' }] },
          { group: '统计', links: [{ r: '/statistics', t: '统计图表' }] },
          { group: '资源', links: [
            { r: '/equipment', t: '设备管理' }, { r: '/boards', t: '展板' }, { r: '/handover', t: '交接班' }, { r: '/customers', t: '客户档案' }] },
          { group: '系统', links: [{ r: '/users', t: '用户管理' }, { r: '/audit', t: '审计日志' }] },
        ],
        experimenter: [
          { group: '工作台', links: [{ r: '/dashboard', t: '工作台' }] },
          { group: '委托管理', links: [
            { r: '/orders/query', t: '委托查询' }, { r: '/review', t: '委托审核' }, { r: '/cases', t: '测试用例库' }] },
          { group: '实验管理', links: [
            { r: '/samples', t: '样品管理' }, { r: '/schedule', t: '实验排期' }, { r: '/expstart', t: '实验开始' }, { r: '/exptrack', t: '实验跟踪' }, { r: '/expend', t: '实验结束' }] },
          { group: '报告', links: [{ r: '/reports', t: '实验报告' }] },
          { group: '统计', links: [{ r: '/statistics', t: '统计图表' }] },
          { group: '资源', links: [{ r: '/boards', t: '展板' }, { r: '/handover', t: '交接班' }, { r: '/customers', t: '客户档案' }] },
        ],
        entruster: [
          { group: '委托', links: [{ r: '/orders/new', t: '委托申请' }, { r: '/orders/query', t: '委托查询' }, { r: '/cases', t: '测试用例库' }] },
        ],
      };
      return menus[state.role] || menus.entruster;
    },
    title() {
      const m = {
        '/dashboard': '工作台', '/orders/new': '委托申请', '/orders/query': '委托查询', '/review': '委托审核',
        '/samples': '样品管理', '/schedule': '实验排期', '/expstart': '实验开始', '/exptrack': '实验跟踪', '/expend': '实验结束', '/reports': '实验报告',
        '/equipment': '设备管理', '/boards': '展板', '/handover': '交接班', '/statistics': '统计图表',
        '/customers': '客户档案', '/audit': '审计日志', '/users': '用户管理', '/cases': '测试用例库',
      };
      return m[state.route] || '工作台';
    },
  },
  data: () => ({ notifCount: 0, notifs: [], showNotif: false, showPwd: false, pwd: { old_password: '', new_password: '' } }),
  methods: {
    navigate, logout,
    async loadNotifCount() { try { this.notifCount = (await api('/api/notifications/unread-count')).count; } catch (e) {} },
    async openNotif() {
      this.showNotif = !this.showNotif;
      if (this.showNotif) { try { this.notifs = await api('/api/notifications'); } catch (e) {} }
    },
    async markRead(n) {
      if (!n.is_read) { await api('/api/notifications/' + n.id + '/read', 'POST'); this.loadNotifCount(); }
      if (n.order_id) { navigate('/orders/query'); this.showNotif = false; }
    },
    async markAllRead() { await api('/api/notifications/read-all', 'POST'); this.notifs.forEach(n => n.is_read = true); this.loadNotifCount(); },
    async changePwd() {
      try {
        if (!this.pwd.old_password || !this.pwd.new_password) { toast('请填写新旧密码', 'error'); return; }
        await api('/api/auth/change-password', 'POST', this.pwd);
        this.showPwd = false; this.pwd = { old_password: '', new_password: '' }; toast('密码已修改', 'success');
      } catch (e) { toast(e.message, 'error'); }
    },
  },
  mounted() { this.loadNotifCount(); },
  template: `
  <div class="layout">
    <div class="sidebar">
      <div class="brand"><span>LIMS</span><small>实验室信息管理系统</small></div>
      <div class="nav">
        <template v-for="g in nav">
          <div class="group">{{g.group}}</div>
          <a v-for="l in g.links" :class="{active: state.route===l.r}" @click="navigate(l.r)">{{l.t}}</a>
        </template>
      </div>
    </div>
    <div class="main">
      <div class="topbar">
        <div class="title">{{title}}</div>
        <div class="user">
          <div class="notif">
            <span class="bell" @click="openNotif">🔔</span><span class="badge-dot" v-if="notifCount">{{notifCount}}</span>
            <div class="notif-panel" v-if="showNotif" @click.stop>
              <div class="notif-head"><b>通知</b><a class="btn link sm" @click="markAllRead">全部已读</a></div>
              <div class="notif-item" v-for="n in notifs" :key="n.id" :class="{unread: !n.is_read}" @click="markRead(n)">
                <div class="notif-title">{{n.title}}</div>
                <div class="notif-content">{{n.content}}</div>
                <div class="notif-time">{{fmtDT(n.created_at)}}</div>
              </div>
              <div v-if="!notifs.length" class="notif-empty">暂无通知</div>
            </div>
          </div>
          <span>{{state.name}}</span><span class="role-tag">{{roleText(state.role)}}</span>
          <button class="btn sm" @click="showPwd=true">改密</button>
          <button class="btn sm" @click="logout">退出</button>
        </div>
      </div>
      <div class="content">
        <dashboard v-if="state.route==='/dashboard'"></dashboard>
        <order-new v-else-if="state.route==='/orders/new'"></order-new>
        <order-query v-else-if="state.route==='/orders/query'"></order-query>
        <review-view v-else-if="state.route==='/review'"></review-view>
        <samples-view v-else-if="state.route==='/samples'"></samples-view>
        <schedule-view v-else-if="state.route==='/schedule'"></schedule-view>
        <exp-start-view v-else-if="state.route==='/expstart'"></exp-start-view>
        <exp-track-view v-else-if="state.route==='/exptrack'"></exp-track-view>
        <exp-end-view v-else-if="state.route==='/expend'"></exp-end-view>
        <reports-view v-else-if="state.route==='/reports'"></reports-view>
        <equipment-view v-else-if="state.route==='/equipment'"></equipment-view>
        <boards-view v-else-if="state.route==='/boards'"></boards-view>
        <handover-view v-else-if="state.route==='/handover'"></handover-view>
        <statistics-view v-else-if="state.route==='/statistics'"></statistics-view>
        <customers-view v-else-if="state.route==='/customers'"></customers-view>
        <audit-view v-else-if="state.route==='/audit'"></audit-view>
        <users-view v-else-if="state.route==='/users'"></users-view>
        <testcase-library v-else-if="state.route==='/cases'"></testcase-library>
      </div>
    </div>
    <div class="modal-mask" v-if="showPwd" @click.self="showPwd=false">
      <div class="modal" style="width:380px">
        <h3>修改密码</h3>
        <div class="form-group"><label>原密码</label><input type="password" v-model="pwd.old_password"></div>
        <div class="form-group"><label>新密码</label><input type="password" v-model="pwd.new_password"></div>
        <div class="modal-actions"><button class="btn" @click="showPwd=false">取消</button><button class="btn primary" @click="changePwd">确认修改</button></div>
      </div>
    </div>
  </div>`,
};
function roleText(r) { return { admin: '管理员', experimenter: '实验员', entruster: '委托人' }[r] || r; }

/* ---------------- 工作台 ---------------- */
const Dashboard = {
  data: () => ({ stats: {}, pending: [], todo: [], expiring: [] }),
  methods: {
    async load() {
      const [s, w] = await Promise.all([api('/api/dashboard/stats'), api('/api/dashboard/workbench')]);
      this.stats = s; this.pending = w.pending; this.todo = w.todo;
      try { this.expiring = await api('/api/equipment/expiring/list?days=30'); } catch (e) {}
    },
    badge,
  },
  mounted() { this.load(); },
  template: `
  <div>
    <div class="grid-stats">
      <div class="stat b"><div class="num">{{stats.total_orders||0}}</div><div class="label">委托单总数</div></div>
      <div class="stat"><div class="num">{{stats.pending_review||0}}</div><div class="label">待审核</div></div>
      <div class="stat o"><div class="num">{{stats.running||0}}</div><div class="label">实验中</div></div>
      <div class="stat g"><div class="num">{{stats.finished||0}}</div><div class="label">已完成</div></div>
      <div class="stat r"><div class="num">{{stats.rejected||0}}</div><div class="label">已否决</div></div>
      <div class="stat"><div class="num">{{stats.total_equipment||0}}</div><div class="label">设备</div></div>
      <div class="stat"><div class="num">{{stats.total_samples||0}}</div><div class="label">样品</div></div>
    </div>
    <div class="two-col">
      <div class="card">
        <h3>待审核委托</h3>
        <table class="tbl"><thead><tr><th>编号</th><th>委托单位</th><th>委托人</th><th>检测项目</th><th>委托时间</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="o in pending" :key="o.id">
            <td>{{o.order_no}}</td><td>{{o.entrust_org}}</td><td>{{o.entruster}}</td><td>{{o.test_item}}</td><td>{{fmtD(o.created_at)}}</td>
            <td><button class="btn link" @click="navigate('/review')">审核</button></td>
          </tr>
          <tr v-if="!pending.length"><td colspan="6" class="empty">暂无待审核委托</td></tr>
        </tbody></table>
      </div>
      <div class="card">
        <h3>待做实验</h3>
        <table class="tbl"><thead><tr><th>实验编号</th><th>产品型号</th><th>检测项目</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="o in todo" :key="o.id">
            <td>{{o.experiment_no||'-'}}</td><td>{{o.sample_model}}</td><td>{{o.test_item}}</td>
            <td v-html="badge(o.status)"></td>
            <td><button class="btn link" @click="navigate('/expstart')">处理</button></td>
          </tr>
          <tr v-if="!todo.length"><td colspan="5" class="empty">暂无待做实验</td></tr>
        </tbody></table>
      </div>
    </div>
    <div class="card" v-if="expiring.length">
      <h3>设备到期提醒（30天内）</h3>
      <table class="tbl"><thead><tr><th>设备名称</th><th>编号</th><th>校准有效期</th><th>剩余天数</th></tr></thead>
      <tbody>
        <tr v-for="e in expiring" :key="e.id">
          <td>{{e.name}}</td><td>{{e.code||'-'}}</td><td>{{fmtD(e.valid_to)}}</td><td>{{e.days_left}} 天</td>
        </tr>
      </tbody></table>
    </div>
  </div>`,
};

/* ---------------- 委托申请 ---------------- */
const OrderNew = {
  data: () => ({ form: emptyOrder(), results: [], caseGroups: [], activeGroupId: null, mode: 'manual', images: [], copiedImages: [] }),
  computed: {
    activeGroupCases() {
      const g = this.caseGroups.find(x => x.id === this.activeGroupId);
      return g ? (g.cases || []) : [];
    },
    selectedCases() {
      return this.caseGroups.flatMap(g => g.cases || []).filter(c => c.checked);
    },
  },
  methods: {
    async submit() {
      // 公共必填项（数量/单位仅手动方式需填写，勾选方式由用例带出）
      const required = [
        ['entrust_org', '委托单位'], ['entruster', '委托人'],
        ['sample_model', 'DHD型号'], ['test_stage', '测试阶段'],
        ['phone', '联系电话'], ['email', 'DHD邮箱'], ['sample_dispose', '样品处理'],
      ];
      if (this.mode === 'manual') {
        required.push(['sample_count', '数量'], ['sample_unit', '单位']);
      }
      for (const [k, label] of required) {
        if (!this.form[k]) { toast('请填写：' + label, 'error'); return; }
      }
      if (this.mode === 'manual' && this.form.sample_count && Number(this.form.sample_count) < 1) { toast('样品数量至少为 1', 'error'); return; }
      try {
        const results = [];
        if (this.mode === 'case') {
          const cases = this.selectedCases;
          if (!cases.length) { toast('请至少勾选一个测试项', 'error'); return; }
          // 每个勾选的用例各生成一份委托单，数量/单位由用例带出，其它字段复制
          for (const c of cases) {
            const payload = { ...this.form, test_item: c.test_item, test_condition: c.test_condition, criteria: c.criteria, sample_count: c.count, sample_unit: c.unit, case_id: c.id, required_start: this.form.required_start || null };
            results.push(await api('/api/orders', 'POST', payload));
          }
          toast('已生成 ' + results.length + ' 份委托单', 'success');
        } else {
          if (!this.form.test_item) { toast('请填写：检测项目', 'error'); return; }
          const payload = { ...this.form, required_start: this.form.required_start || null };
          if (this.copiedImages.length) payload.copy_image_ids = this.copiedImages.map(im => im.id);
          const created = await api('/api/orders', 'POST', payload);
          results.push(created);
          if (this.images.length) {
            try {
              for (const im of this.images) await uploadOrderImage(created.id, im.file);
            } catch (e) { toast('委托已提交，但附件图片上传失败：' + e.message, 'error'); }
          }
          this.images.forEach(im => URL.revokeObjectURL(im.url));
          this.images = [];
          this.copiedImages = [];
          toast('提交成功', 'success');
        }
        this.results = results;
      } catch (e) { toast(e.message, 'error'); }
    },
    switchMode(m) { this.mode = m; },
    reset() {
      this.form = emptyOrder();
      this.results = [];
      this.images.forEach(im => URL.revokeObjectURL(im.url));
      this.images = [];
      this.copiedImages = [];
      this.caseGroups.forEach(g => (g.cases || []).forEach(c => c.checked = false));
    },
    onPickImages(e) {
      const files = Array.from(e.target.files || []);
      files.forEach(f => {
        if (!f.type || !f.type.startsWith('image/')) { toast('仅支持图片文件', 'error'); return; }
        if (f.size > 5 * 1024 * 1024) { toast(`「${f.name}」超过 5MB，已跳过`, 'error'); return; }
        this.images.push({ file: f, url: URL.createObjectURL(f) });
      });
      e.target.value = '';
    },
    removeImage(i) { URL.revokeObjectURL(this.images[i].url); this.images.splice(i, 1); },
    removeCopiedImage(i) { this.copiedImages.splice(i, 1); },
  },
  async mounted() {
    // 「复制实验委托申请」：带入委托查询里点击复制的内容
    if (state.orderPrefill) {
      const pf = state.orderPrefill;
      this.copiedImages = pf.copyImages || [];
      delete pf.copyImages;
      this.form = { ...this.form, ...pf };
      state.orderPrefill = null;
    }
    // 登录的委托人：自动带出本人姓名，确保委托单与账号绑定
    if (state.token && state.role === 'entruster' && !this.form.entruster) {
      this.form.entruster = state.name;
    }
    if (state.token) {
      try {
        const groups = await api('/api/cases/groups?with_cases=true');
        groups.forEach(g => (g.cases || []).forEach(c => c.checked = false));
        this.caseGroups = groups;
      } catch (e) {}
    }
  },
  template: `
  <div class="card">
    <h3>实验委托申请 <span style="font-size:12px;color:#c62828">（红色标记为必填项）</span></h3>
    <div class="tabs">
      <div class="tab" :class="{active: mode==='manual'}" @click="switchMode('manual')">手动填写委托</div>
      <div class="tab" :class="{active: mode==='case'}" @click="switchMode('case')">从用例库勾选</div>
    </div>
    <div v-if="results.length" style="background:#e6f4ea;padding:12px;border-radius:6px;margin-bottom:14px">
      委托申请提交成功！共生成 <b>{{results.length}}</b> 份委托单：
      <div v-for="(r, i) in results" :key="i" style="margin-top:2px">委托单编号：<b>{{r.order_no}}</b></div>
    </div>
    <div class="form-row" v-if="mode==='case' && caseGroups.length" style="background:#f5f7fa;padding:10px;border-radius:6px;margin-bottom:14px;align-items:flex-start">
      <div class="form-group" style="flex:0 0 210px;margin:0">
        <label>选择客户分组</label>
        <select v-model="activeGroupId">
          <option :value="null">—— 选择客户分组 ——</option>
          <option v-for="g in caseGroups" :key="g.id" :value="g.id">{{g.name}}</option>
        </select>
      </div>
      <div class="form-group" style="flex:1;margin:0">
        <label>勾选测试项（已选 {{selectedCases.length}} 项，提交后每个用例各生成一份委托单）</label>
        <div class="case-check-list">
          <label v-for="c in activeGroupCases" :key="c.id" class="case-check" :class="{checked: c.checked}">
            <input type="checkbox" v-model="c.checked">
            <span class="case-check-name">{{c.test_item}}</span>
            <span class="case-check-hint">×{{c.count}}{{c.unit}}</span>
            <span class="case-check-hint" v-if="c.criteria">（{{c.criteria}}）</span>
          </label>
          <div v-if="!activeGroupCases.length" class="empty" style="padding:10px">该分组暂无用例</div>
        </div>
      </div>
    </div>
    <div v-if="mode==='case' && !caseGroups.length" style="background:#fff7e6;padding:10px;border-radius:6px;margin-bottom:14px;color:#b26a00">
      测试用例库为空，请先到「测试用例库」页面建立客户分组和用例，再回来勾选提交。
    </div>
    <div class="form-row">
      <div class="form-group"><label><span class="req">*</span>委托单位</label><select v-model="form.entrust_org"><option>音频研发中心</option><option>创新事业部</option><option>国内事业部</option><option>高端事业部</option><option>营销中心</option><option>供应链中心</option><option>工程质量中心</option></select></div>
      <div class="form-group"><label><span class="req">*</span>委托人</label><input v-model="form.entruster"></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label><span class="req">*</span>DHD型号</label><input v-model="form.sample_model"></div>
      <div class="form-group"><label>客户型号</label><input v-model="form.customer_model"></div>
    </div>
    <div class="form-row">
      <div class="form-group" v-if="mode==='manual'"><label><span class="req">*</span>检测项目</label><input v-model="form.test_item"></div>
      <div class="form-group" v-if="mode==='manual'"><label>检测项目(英文)</label><input v-model="form.test_item_en"></div>
      <div class="form-group" style="flex:0 0 130px"><label><span class="req">*</span>测试阶段</label><select v-model="form.test_stage"><option>EVT</option><option>DVT</option><option>DVT-2</option><option>DVT-3</option><option>PVT</option><option>PVT-2</option><option>PVT-3</option><option>MP</option><option>二供</option><option>三供</option><option>四供</option><option>五供</option></select></div>
      <div class="form-group" v-if="mode==='manual'" style="flex:0 0 90px"><label><span class="req">*</span>数量</label><input type="number" v-model.number="form.sample_count"></div>
      <div class="form-group" v-if="mode==='manual'" style="flex:0 0 80px"><label><span class="req">*</span>单位</label><input v-model="form.sample_unit"></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>试验原因</label><select v-model="form.test_reason"><option>例行试验</option><option>临时试验</option><option>委托试验</option></select></div>
      <div class="form-group"><label>报告要求</label><select v-model="form.report_lang"><option>中文</option><option>英文</option><option>中英双语</option></select></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label><span class="req">*</span>联系电话</label><input v-model="form.phone"></div>
      <div class="form-group"><label><span class="req">*</span>DHD邮箱</label><input v-model="form.email"></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>样品状态</label><input v-model="form.sample_status"></div>
      <div class="form-group"><label>存放要求</label><input v-model="form.storage_require"></div>
      <div class="form-group"><label><span class="req">*</span>样品处理</label><select v-model="form.sample_dispose"><option>退还</option><option>报废</option><option>留存</option></select></div>
      <div class="form-group"><label>要求完成时间</label><input type="datetime-local" v-model="form.required_start"></div>
    </div>
    <div class="form-group" v-if="mode==='manual'"><label>试验条件</label><textarea v-model="form.test_condition"></textarea></div>
    <div class="form-group" v-if="mode==='manual'"><label>试验条件附图（可多选，单张 ≤5MB）</label>
      <div v-if="copiedImages.length" style="margin-bottom:6px;font-size:12px;color:var(--muted)">已从原单带入 {{copiedImages.length}} 张附图，提交后将随新单复制：</div>
      <div class="img-thumbs" v-if="copiedImages.length" style="margin-bottom:8px">
        <div v-for="(im,i) in copiedImages" :key="'c'+i" style="position:relative">
          <a :href="im.path" target="_blank" :title="im.filename"><img :src="im.path" :alt="im.filename"></a>
          <span @click="removeCopiedImage(i)" style="position:absolute;top:-6px;right:-6px;background:#c62828;color:#fff;border-radius:50%;width:18px;height:18px;line-height:18px;text-align:center;cursor:pointer;font-size:12px">×</span>
        </div>
      </div>
      <input type="file" accept="image/*" multiple @change="onPickImages" style="display:none" ref="imgInput">
      <button class="btn" type="button" @click="$refs.imgInput.click()">选择图片（追加）</button>
      <div class="img-thumbs" v-if="images.length" style="margin-top:8px">
        <div v-for="(im,i) in images" :key="i" style="position:relative">
          <img :src="im.url" :alt="im.file.name" :title="im.file.name">
          <span @click="removeImage(i)" style="position:absolute;top:-6px;right:-6px;background:#c62828;color:#fff;border-radius:50%;width:18px;height:18px;line-height:18px;text-align:center;cursor:pointer;font-size:12px">×</span>
        </div>
      </div>
    </div>
    <div class="form-group" v-if="mode==='manual'"><label>判定标准</label><textarea v-model="form.criteria"></textarea></div>
    <div class="form-group"><label>备注</label><textarea v-model="form.remark"></textarea></div>
    <div style="margin-top:10px">
      <button class="btn primary" @click="submit">提交申请</button>
      <button class="btn" style="margin-left:10px" @click="reset">重置</button>
    </div>
  </div>`,
};
function emptyOrder() {
  return {
    entrust_org: '', entrust_org_en: '', entruster: '', entruster_en: '',
    sample_name: '', sample_name_en: '', test_item: '', test_item_en: '', test_basis: '', test_basis_en: '',
    test_stage: '', sample_model: '', customer_model: '', sample_count: '', sample_unit: '',
    phone: '', email: '', tracker: '', tracker_email: '', test_reason: '例行试验', report_lang: '中文',
    sample_status: '样品正常', storage_require: '常温存放', sample_dispose: '退还',
    test_condition: '', criteria: '', remark: '', required_start: '', case_id: null,
  };
}

/* ---------------- 测试用例库 ---------------- */
async function uploadCaseImage(caseId, file) {
  const fd = new FormData();
  fd.append('file', file);
  const res = await fetch('/api/cases/' + caseId + '/images', {
    method: 'POST',
    headers: { 'Authorization': 'Bearer ' + state.token },
    body: fd,
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) { logout(); throw new Error('未登录或登录已过期'); }
  if (!res.ok) throw new Error((data && data.detail) || '上传失败');
  return data;
}

async function uploadOrderImage(orderId, file) {
  const fd = new FormData();
  fd.append('file', file);
  const headers = {};
  if (state.token) headers['Authorization'] = 'Bearer ' + state.token;
  const res = await fetch('/api/orders/' + orderId + '/images', { method: 'POST', headers, body: fd });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) { logout(); throw new Error('未登录或登录已过期'); }
  if (!res.ok) throw new Error((data && data.detail) || '图片上传失败');
  return data;
}

const TestCaseLibrary = {
  data: () => ({
    groups: [], activeGroupId: null,
    showGroupModal: false, groupForm: { name: '', remark: '' },
    showCaseModal: false, caseForm: {}, editingCaseId: null,
    uploading: false,
  }),
  computed: {
    activeGroup() { return this.groups.find(g => g.id === this.activeGroupId) || null; },
  },
  methods: {
    async load() {
      this.groups = await api('/api/cases/groups?with_cases=true');
      if (!this.activeGroupId && this.groups.length) this.activeGroupId = this.groups[0].id;
      if (this.activeGroupId && !this.groups.find(g => g.id === this.activeGroupId)) {
        this.activeGroupId = this.groups.length ? this.groups[0].id : null;
      }
    },
    selectGroup(g) { this.activeGroupId = g.id; },
    openNewGroup() { this.groupForm = { name: '', remark: '' }; this.showGroupModal = true; },
    async saveGroup() {
      if (!this.groupForm.name.trim()) { toast('请输入分组名（客户名）', 'error'); return; }
      try {
        await api('/api/cases/groups', 'POST', this.groupForm);
        this.showGroupModal = false; toast('分组已创建', 'success'); await this.load();
      } catch (e) { toast(e.message, 'error'); }
    },
    async renameGroup() {
      if (!this.activeGroup) return;
      const name = prompt('新的分组名', this.activeGroup.name);
      if (name == null || !name.trim()) return;
      try { await api('/api/cases/groups/' + this.activeGroup.id, 'PUT', { name }); await this.load(); toast('已重命名', 'success'); }
      catch (e) { toast(e.message, 'error'); }
    },
    async deleteGroup() {
      if (!this.activeGroup) return;
      if (!confirm('删除分组「' + this.activeGroup.name + '」将同时删除其下所有用例与图片，确认？')) return;
      try { await api('/api/cases/groups/' + this.activeGroup.id, 'DELETE'); this.activeGroupId = null; await this.load(); toast('已删除', 'success'); }
      catch (e) { toast(e.message, 'error'); }
    },
    openNewCase() {
      if (!this.activeGroup) { toast('请先选择或创建分组', 'error'); return; }
      this.editingCaseId = null;
      this.caseForm = { group_id: this.activeGroup.id, test_item: '', test_condition: '', criteria: '', count: 1, unit: '只', remark: '' };
      this.showCaseModal = true;
    },
    openEditCase(c) {
      this.editingCaseId = c.id;
      this.caseForm = { group_id: c.group_id, test_item: c.test_item, test_condition: c.test_condition, criteria: c.criteria, count: c.count, unit: c.unit, remark: c.remark };
      this.showCaseModal = true;
    },
    async saveCase() {
      if (!this.caseForm.test_item.trim()) { toast('请填写检测项目', 'error'); return; }
      try {
        if (this.editingCaseId) await api('/api/cases/' + this.editingCaseId, 'PUT', this.caseForm);
        else await api('/api/cases', 'POST', this.caseForm);
        this.showCaseModal = false; toast('已保存', 'success'); await this.load();
      } catch (e) { toast(e.message, 'error'); }
    },
    async deleteCase(c) {
      if (!confirm('删除用例「' + c.test_item + '」及其图片？')) return;
      try { await api('/api/cases/' + c.id, 'DELETE'); await this.load(); toast('已删除', 'success'); }
      catch (e) { toast(e.message, 'error'); }
    },
    async onPickImage(c, e) {
      const file = e.target.files && e.target.files[0];
      e.target.value = '';
      if (!file) return;
      if (this.uploading) return;
      this.uploading = true;
      try { await uploadCaseImage(c.id, file); toast('图片已上传', 'success'); await this.load(); }
      catch (err) { toast(err.message, 'error'); }
      finally { this.uploading = false; }
    },
    async deleteImage(c, img) {
      if (!confirm('删除该图片？')) return;
      try { await api('/api/cases/images/' + img.id, 'DELETE'); await this.load(); toast('已删除图片', 'success'); }
      catch (e) { toast(e.message, 'error'); }
    },
  },
  mounted() { this.load(); },
  template: `
  <div class="card">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
      <h3 style="margin:0">测试用例库</h3>
      <button class="btn primary sm" @click="openNewGroup">+ 新建分组</button>
    </div>
    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:12px">
      <b>客户分组：</b>
      <button v-for="g in groups" :key="g.id" class="btn sm" :class="{primary: g.id===activeGroupId}" @click="selectGroup(g)">{{g.name}}（{{g.case_count}}）</button>
      <span v-if="!groups.length" class="empty" style="margin:0">暂无分组，点击右上角「新建分组」</span>
    </div>

    <div v-if="activeGroup" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
      <div><b>{{activeGroup.name}}</b> <span v-if="activeGroup.remark" style="color:#888;font-size:12px">— {{activeGroup.remark}}</span></div>
      <div>
        <button class="btn sm" @click="renameGroup">重命名</button>
        <button class="btn sm" style="color:#c62828" @click="deleteGroup">删除分组</button>
        <button class="btn primary sm" @click="openNewCase">+ 新建用例</button>
      </div>
    </div>

    <table class="tbl" v-if="activeGroup && activeGroup.cases.length">
      <thead><tr><th style="width:120px">检测项目</th><th style="width:70px">数量</th><th>试验条件</th><th>判定标准</th><th style="width:120px">备注</th><th style="width:190px">图片</th><th style="width:170px">操作</th></tr></thead>
      <tbody>
        <tr v-for="c in activeGroup.cases" :key="c.id">
          <td>{{c.test_item}}</td>
          <td>{{c.count}}{{c.unit}}</td>
          <td style="white-space:pre-wrap">{{c.test_condition || '—'}}</td>
          <td style="white-space:pre-wrap">{{c.criteria || '—'}}</td>
          <td>{{c.remark || '—'}}</td>
          <td>
            <div style="display:flex;gap:4px;flex-wrap:wrap">
              <div v-for="img in c.images" :key="img.id" style="position:relative">
                <a :href="img.path" target="_blank"><img :src="img.path" :title="img.filename" style="width:44px;height:44px;object-fit:cover;border-radius:4px;border:1px solid #ddd;display:block"></a>
                <span @click="deleteImage(c, img)" style="position:absolute;top:-6px;right:-6px;background:#c62828;color:#fff;width:16px;height:16px;border-radius:50%;line-height:16px;text-align:center;font-size:12px;cursor:pointer">×</span>
              </div>
            </div>
          </td>
          <td>
            <button class="btn link" @click="openEditCase(c)">编辑</button>
            <label class="btn link" style="cursor:pointer">传图<input type="file" accept="image/*" style="display:none" @change="onPickImage(c, $event)"></label>
            <button class="btn link" style="color:#c62828" @click="deleteCase(c)">删除</button>
          </td>
        </tr>
      </tbody>
    </table>
    <div v-else-if="activeGroup" class="empty">该分组暂无用例，点击「+ 新建用例」添加</div>
    <div v-else class="empty">请先选择或新建一个客户分组</div>

    <div class="modal-mask" v-if="showGroupModal" @click.self="showGroupModal=false">
      <div class="modal" style="width:420px">
        <h3>新建分组</h3>
        <div class="form-group"><label>分组名（客户名）</label><input v-model="groupForm.name" placeholder="如：华为 / 小米 / 客户A"></div>
        <div class="form-group"><label>备注</label><input v-model="groupForm.remark"></div>
        <div class="modal-actions"><button class="btn" @click="showGroupModal=false">取消</button><button class="btn primary" @click="saveGroup">保存</button></div>
      </div>
    </div>

    <div class="modal-mask" v-if="showCaseModal" @click.self="showCaseModal=false">
      <div class="modal" style="width:520px">
        <h3>{{editingCaseId ? '编辑用例' : '新建用例'}}</h3>
        <div class="form-group"><label>检测项目</label><input v-model="caseForm.test_item" placeholder="如：跌落试验"></div>
        <div class="form-group"><label>试验条件</label><textarea v-model="caseForm.test_condition" placeholder="如：1.5m 高度，3 个方向各 1 次"></textarea></div>
        <div class="form-group"><label>判定标准</label><textarea v-model="caseForm.criteria" placeholder="如：无破损、无变形、功能正常"></textarea></div>
        <div class="form-row">
          <div class="form-group" style="flex:0 0 120px"><label>数量</label><input type="number" v-model.number="caseForm.count"></div>
          <div class="form-group" style="flex:1"><label>单位</label><input v-model="caseForm.unit" placeholder="如：只 / 台 / 批"></div>
        </div>
        <div class="form-group"><label>备注</label><input v-model="caseForm.remark"></div>
        <div class="modal-actions"><button class="btn" @click="showCaseModal=false">取消</button><button class="btn primary" @click="saveCase">保存</button></div>
      </div>
    </div>
  </div>`,
};

/* ---------------- 委托查询 ---------------- */
const OrderQuery = {
  data: () => ({ order_no: '', phone: '', list: [], status: '', keyword: '', all: [], showEdit: false, edit: null, editForm: {}, detail: null, ooEnabled: false, ooUrl: '', ooShow: false, ooEditor: null, ooKind: 'orders', ooKey: '' }),
  methods: {
    async search() {
      if (!state.token) {
        if (!this.order_no && !this.phone) { toast('请输入委托单编号或联系电话', 'error'); return; }
        this.list = await api(`/api/orders/query?order_no=${this.order_no}&phone=${this.phone}`);
        return;
      }
      const q = new URLSearchParams();
      if (this.status) q.set('status', this.status);
      if (this.keyword) q.set('keyword', this.keyword);
      this.all = await api('/api/orders?' + q.toString());
    },
    isAdmin() { return state.role === 'admin'; },
    canEdit(o) {
      if (!this.isAdmin()) return false;
      if (o.status !== '待审核') return false;
      return true;
    },
    openEdit(o) {
      this.edit = o;
      this.editForm = {
        entrust_org: o.entrust_org, entrust_org_en: o.entrust_org_en,
        entruster: o.entruster, entruster_en: o.entruster_en,
        sample_name: o.sample_name, sample_name_en: o.sample_name_en,
        test_item: o.test_item, test_item_en: o.test_item_en,
        test_basis: o.test_basis, test_basis_en: o.test_basis_en,
        test_stage: o.test_stage, sample_model: o.sample_model, customer_model: o.customer_model,
        sample_count: o.sample_count, sample_unit: o.sample_unit,
        phone: o.phone, email: o.email, tracker: o.tracker, tracker_email: o.tracker_email,
        test_reason: o.test_reason, report_lang: o.report_lang,
        sample_status: o.sample_status, storage_require: o.storage_require,
        sample_dispose: o.sample_dispose, test_condition: o.test_condition, criteria: o.criteria, remark: o.remark,
        required_start: o.required_start ? String(o.required_start).slice(0, 16) : '',
      };
      this.showEdit = true;
    },
    async saveEdit() {
      try {
        if (!this.editForm.sample_count || Number(this.editForm.sample_count) < 1) { toast('样品数量至少为 1', 'error'); return; }
        const payload = { ...this.editForm, required_start: this.editForm.required_start || null };
        await api('/api/orders/' + this.edit.id, 'PUT', payload);
        toast('修改成功', 'success'); this.showEdit = false; this.search();
      } catch (e) { toast(e.message, 'error'); }
    },
    async remove(o) {
      if (!confirm(`确认删除委托单 ${o.order_no}？删除后不可恢复。`)) return;
      try {
        await api('/api/orders/' + o.id, 'DELETE');
        toast('已删除', 'success'); this.search();
      } catch (e) { toast(e.message, 'error'); }
    },
    openDetail(o) {
      this.detail = o;
      // 登录的审核/实验员：拉取完整详情以带出附件图片（免登录查询接口无 images 字段）
      if (state.token && (state.role === 'admin' || state.role === 'experimenter')) {
        api('/api/orders/' + o.id).then(d => { this.detail = d; }).catch(() => {});
      }
    },
    copyToNew() {
      const o = this.detail;
      if (!o) return;
      state.orderPrefill = {
        entrust_org: o.entrust_org || '', entrust_org_en: o.entrust_org_en || '',
        entruster: o.entruster || '', entruster_en: o.entruster_en || '',
        sample_name: o.sample_name || '', sample_name_en: o.sample_name_en || '',
        test_item: o.test_item || '', test_item_en: o.test_item_en || '',
        test_basis: o.test_basis || '', test_basis_en: o.test_basis_en || '',
        test_stage: o.test_stage || '', sample_model: o.sample_model || '', customer_model: o.customer_model || '',
        sample_count: o.sample_count != null ? o.sample_count : '', sample_unit: o.sample_unit || '',
        phone: o.phone || '', email: o.email || '', tracker: o.tracker || '', tracker_email: o.tracker_email || '',
        test_reason: o.test_reason || '例行试验', report_lang: o.report_lang || '中文',
        sample_status: o.sample_status || '样品正常', storage_require: o.storage_require || '常温存放', sample_dispose: o.sample_dispose || '退还',
        test_condition: o.test_condition || '', criteria: o.criteria || '', remark: o.remark || '',
        required_start: o.required_start ? String(o.required_start).slice(0, 16) : '',
        case_id: null,
        copyImages: (o.images || []).map(im => ({ id: im.id, path: im.path, filename: im.filename })),
      };
      this.detail = null;
      navigate('/orders/new');
      toast('已复制到「委托申请」，请核对后提交', 'success');
    },
    badge, fmtDT,
    async checkOO() {
      try { const r = await api('/api/oo/info'); this.ooEnabled = !!r.enabled; this.ooUrl = r.url || ''; }
      catch (e) { this.ooEnabled = false; }
    },
    async openExcel(kind) {
      try {
        const config = await api('/api/export/online?kind=' + encodeURIComponent(kind), 'POST');
        this.ooKind = kind;
        this.ooKey = (config.document && config.document.key) || '';
        this.ooShow = true;
        this.$nextTick(() => {
          loadOO(this.ooUrl).then(D => {
            if (!D) { toast('加载 OnlyOffice 编辑器脚本失败', 'error'); return; }
            if (this.ooEditor) { try { this.ooEditor.destroyEditor(); } catch (e) {} this.ooEditor = null; }
            this.ooEditor = new D.DocEditor('onlyoffice-editor', config);
          });
        });
      } catch (e) { toast(e.message, 'error'); }
    },
    closeOO() {
      if (this.ooEditor) { try { this.ooEditor.destroyEditor(); } catch (e) {} this.ooEditor = null; }
      this.ooShow = false;
    },
    downloadExcel() {
      if (!this.ooKey) { toast('请先在表格中编辑保存', 'error'); return; }
      const headers = {};
      if (state.token) headers['Authorization'] = 'Bearer ' + state.token;
      fetch('/api/export/online/download?key=' + encodeURIComponent(this.ooKey), { headers })
        .then(res => {
          if (res.status === 401) { logout(); throw new Error('未登录或登录已过期'); }
          if (!res.ok) return res.json().then(d => { throw new Error((d && d.detail) || '下载失败'); });
          return res.blob();
        })
        .then(blob => {
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url; a.download = this.ooKind + '_编辑后.xlsx';
          document.body.appendChild(a); a.click(); a.remove();
          setTimeout(() => URL.revokeObjectURL(url), 2000);
        })
        .catch(e => toast(e.message, 'error'));
    },
  },
  mounted() { if (state.token) this.search(); this.checkOO(); },
  template: `
  <div class="card">
    <h3>实验委托查询</h3>
    <div v-if="!state.token">
      <div class="toolbar">
        <input v-model="order_no" placeholder="委托单编号"><input v-model="phone" placeholder="联系电话">
        <button class="btn primary" @click="search">查询</button>
      </div>
      <table class="tbl"><thead><tr><th>编号</th><th>委托单位</th><th>委托人</th><th>检测项目</th><th>状态</th><th>备注</th><th>委托时间</th></tr></thead>
      <tbody>
        <tr v-for="o in list" :key="o.id">
          <td><a class="link" @click="openDetail(o)">{{o.order_no}}</a></td><td>{{o.entrust_org}}</td><td>{{o.entruster}}</td>
          <td>{{o.test_item}}</td><td v-html="badge(o.status)"></td><td>{{ o.status === '已否决' ? o.reject_reason : '' }}</td><td>{{fmtD(o.created_at)}}</td>
        </tr>
        <tr v-if="!list.length"><td colspan="7" class="empty">输入条件后查询</td></tr>
      </tbody></table>
    </div>
    <div v-else>
      <div class="toolbar">
        <select v-model="status"><option value="">全部状态</option>
          <option v-for="s in ['待审核','已审核','已排期','实验中','已完成','已否决']" :key="s" :value="s">{{s}}</option></select>
        <input v-model="keyword" placeholder="编号/委托人/单位/型号/样品名"><button class="btn primary" @click="search">查询</button>
        <button class="btn" v-if="ooEnabled" @click="openExcel('orders')">导出Excel(在线编辑)</button>
      </div>
      <table class="tbl"><thead><tr><th>委托编号</th><th>实验编号</th><th>委托单位</th><th>委托人</th><th>检测项目</th><th>状态</th><th>备注</th><th>委托时间</th><th v-if="isAdmin()">操作</th></tr></thead>
      <tbody>
        <tr v-for="o in all" :key="o.id">
          <td><a class="link" @click="openDetail(o)">{{o.order_no}}</a></td><td>{{o.experiment_no||'-'}}</td><td>{{o.entrust_org}}</td><td>{{o.entruster}}</td>
          <td>{{o.test_item}}</td><td v-html="badge(o.status)"></td><td>{{ o.status === '已否决' ? o.reject_reason : '' }}</td><td>{{fmtD(o.created_at)}}</td>
          <td v-if="isAdmin()">
            <button class="btn sm" v-if="canEdit(o)" @click="openEdit(o)">修改</button>
            <button class="btn danger sm" v-if="canEdit(o)" @click="remove(o)">删除</button>
          </td>
        </tr>
        <tr v-if="!all.length"><td :colspan="isAdmin() ? 9 : 8" class="empty">暂无数据</td></tr>
      </tbody></table>
    </div>
  </div>
  <div class="modal-mask" v-if="showEdit" @click.self="showEdit=false">
    <div class="modal" style="width:860px">
      <h3>修改委托单 —— {{edit.order_no}}</h3>
      <div class="form-row">
        <div class="form-group"><label><span class="req">*</span>委托单位</label><select v-model="editForm.entrust_org"><option>音频研发中心</option><option>创新事业部</option><option>国内事业部</option><option>高端事业部</option><option>营销中心</option><option>供应链中心</option><option>工程质量中心</option></select></div>
        <div class="form-group"><label>委托人</label><input v-model="editForm.entruster"></div>
        <div class="form-group"><label><span class="req">*</span>DHD型号</label><input v-model="editForm.sample_model"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label><span class="req">*</span>检测项目</label><input v-model="editForm.test_item"></div>
        <div class="form-group" style="flex:0 0 130px"><label><span class="req">*</span>测试阶段</label><select v-model="editForm.test_stage"><option>EVT</option><option>DVT</option><option>DVT-2</option><option>DVT-3</option><option>PVT</option><option>PVT-2</option><option>PVT-3</option><option>MP</option><option>二供</option><option>三供</option><option>四供</option><option>五供</option></select></div>
        <div class="form-group" style="flex:0 0 80px"><label><span class="req">*</span>数量</label><input type="number" v-model.number="editForm.sample_count"></div>
        <div class="form-group" style="flex:0 0 80px"><label><span class="req">*</span>单位</label><input v-model="editForm.sample_unit"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label><span class="req">*</span>联系电话</label><input v-model="editForm.phone"></div>
        <div class="form-group"><label><span class="req">*</span>邮箱</label><input v-model="editForm.email"></div>
        <div class="form-group"><label>样品处理</label><select v-model="editForm.sample_dispose"><option>退还</option><option>报废</option><option>留存</option></select></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>样品状态</label><input v-model="editForm.sample_status"></div>
        <div class="form-group"><label>存放要求</label><input v-model="editForm.storage_require"></div>
        <div class="form-group"><label>要求完成时间</label><input type="datetime-local" v-model="editForm.required_start"></div>
      </div>
      <div class="form-group"><label>试验条件</label><textarea v-model="editForm.test_condition"></textarea></div>
      <div class="form-group"><label>判定标准</label><textarea v-model="editForm.criteria"></textarea></div>
      <div class="form-group"><label>备注</label><textarea v-model="editForm.remark"></textarea></div>
      <div class="modal-actions">
        <button class="btn" @click="showEdit=false">取消</button>
        <button class="btn primary" @click="saveEdit">保存修改</button>
      </div>
    </div>
  </div>
  <div class="modal-mask" v-if="detail" @click.self="detail=null">
    <div class="modal" style="width:860px">
      <h3>实验委托申请 —— {{detail.order_no}}</h3>
      <table class="tbl"><tbody>
        <tr><td class="detail-lbl">委托编号</td><td>{{detail.order_no}}</td><td class="detail-lbl">状态</td><td v-html="badge(detail.status)"></td></tr>
        <tr><td class="detail-lbl">委托单位</td><td>{{detail.entrust_org}}</td><td class="detail-lbl">委托人</td><td>{{detail.entruster}}</td></tr>
        <tr><td class="detail-lbl">DHD型号</td><td>{{detail.sample_model}}</td><td class="detail-lbl">客户型号</td><td>{{detail.customer_model || '-'}}</td></tr>
        <tr><td class="detail-lbl">样品名称</td><td>{{detail.sample_name || '-'}}</td><td class="detail-lbl">数量</td><td>{{detail.sample_count}}{{detail.sample_unit}}</td></tr>
        <tr><td class="detail-lbl">检测项目</td><td>{{detail.test_item}}</td><td class="detail-lbl">测试阶段</td><td>{{detail.test_stage}}</td></tr>
        <tr><td class="detail-lbl">检测依据</td><td colspan="3">{{detail.test_basis || '-'}}</td></tr>
        <tr><td class="detail-lbl">试验原因</td><td>{{detail.test_reason || '-'}}</td><td class="detail-lbl">报告要求</td><td>{{detail.report_lang || '-'}}</td></tr>
        <tr><td class="detail-lbl">联系电话</td><td>{{detail.phone}}</td><td class="detail-lbl">邮箱</td><td>{{detail.email}}</td></tr>
        <tr><td class="detail-lbl">样品状态</td><td>{{detail.sample_status || '-'}}</td><td class="detail-lbl">存放要求</td><td>{{detail.storage_require || '-'}}</td></tr>
        <tr><td class="detail-lbl">样品处理</td><td>{{detail.sample_dispose || '-'}}</td><td class="detail-lbl">要求完成时间</td><td>{{fmtDT(detail.required_start) || '-'}}</td></tr>
        <tr v-if="detail.tracker || detail.tracker_email"><td class="detail-lbl">跟踪人</td><td>{{detail.tracker || '-'}}</td><td class="detail-lbl">跟踪人邮箱</td><td>{{detail.tracker_email || '-'}}</td></tr>
        <tr v-if="detail.test_condition"><td class="detail-lbl">试验条件</td><td colspan="3" style="white-space:pre-wrap">{{detail.test_condition}}</td></tr>
        <tr v-if="detail.images && detail.images.length"><td class="detail-lbl">试验条件附图</td><td colspan="3"><div class="img-thumbs"><a v-for="im in detail.images" :key="im.id" :href="im.path" target="_blank" :title="im.filename"><img :src="im.path" :alt="im.filename"></a></div></td></tr>
        <tr v-if="detail.criteria"><td class="detail-lbl">判定标准</td><td colspan="3" style="white-space:pre-wrap">{{detail.criteria}}</td></tr>
        <tr v-if="detail.reject_reason"><td class="detail-lbl">否决原因</td><td colspan="3" style="color:#c62828">{{detail.reject_reason}}</td></tr>
        <tr v-if="detail.remark"><td class="detail-lbl">备注</td><td colspan="3" style="white-space:pre-wrap">{{detail.remark}}</td></tr>
        <tr><td class="detail-lbl">委托时间</td><td colspan="3">{{fmtDT(detail.created_at)}}</td></tr>
      </tbody></table>
      <div class="modal-actions"><button class="btn primary" @click="copyToNew">复制实验委托申请</button><button class="btn" @click="detail=null">关闭</button></div>
    </div>
  </div>
  <div class="modal-mask" v-if="ooShow" @click.self="closeOO()">
    <div class="modal oo-modal">
      <div class="toolbar" style="margin-bottom:10px">
        <h3 style="flex:1;margin:0">在线编辑表格 —— {{ooKind}}</h3>
        <span style="font-size:12px;color:var(--muted)">编辑后点「下载Excel」导出，未保存前不可下载</span>
        <button class="btn sm" @click="downloadExcel">下载Excel</button>
        <button class="btn sm" @click="closeOO()">关闭</button>
      </div>
      <div id="onlyoffice-editor" class="oo-editor-host"></div>
    </div>
  </div>`,
};

/* ---------------- 委托审核 ---------------- */
const ReviewView = {
  data: () => ({ list: [], detail: null, reviewers: [], allEq: [], showModal: false, feeRows: [], rejectReason: '', current: null }),
  methods: {
    async load() {
      this.list = await api('/api/orders?status=待审核');
      this.reviewers = (await api('/api/auth/users')).filter(u => u.role !== 'entruster');
    },
    async open(o) {
      this.current = o; this.detail = await api('/api/orders/' + o.id);
      this.reviewers = (await api('/api/auth/users')).filter(u => u.role !== 'entruster');
      this.allEq = await api('/api/equipment');
      this.rejectReason = ''; this.showModal = true;
      this.feeRows = [this.newFee()];
    },
    addFee() { this.feeRows.push(this.newFee()); },
    newFee() { return { test_item: this.detail.test_item, equipment_id: null, open_fee: 0, power_fee: 0, depreciation_fee: 0, consumable_fee: 0, test_time: 0, test_count: 1, quantity: this.detail.sample_count || 1, discount: 1, service_fee: 0 }; },
    onEqChange(r) {
      const eq = this.allEq.find(e => e.id === r.equipment_id);
      if (eq) { r.open_fee = eq.open_fee; r.power_fee = eq.power_fee; r.depreciation_fee = eq.depreciation_fee; r.consumable_fee = eq.consumable_fee; }
      else { r.open_fee = 0; r.power_fee = 0; r.depreciation_fee = 0; r.consumable_fee = 0; }
    },
    rowAmount(r) {
      const open_fee = Number(r.open_fee) || 0;
      const power_fee = Number(r.power_fee) || 0;
      const dep_fee = Number(r.depreciation_fee) || 0;
      const cons_fee = Number(r.consumable_fee) || 0;
      const test_time = Number(r.test_time) || 0;
      const test_count = Number(r.test_count) || 1;
      const discount = Number(r.discount) || 1;
      const service_fee = Number(r.service_fee) || 0;
      const amount = open_fee + (power_fee + dep_fee + cons_fee) * test_time * test_count * discount + service_fee;
      return Math.round(amount * 100) / 100;
    },
    async approve() {
      const missing = [];
      if (!this.detail || !this.detail.reviewer_id) missing.push('实验员');
      if (!this.feeRows.some(r => r.equipment_id)) missing.push('费用明细（选择设备）');
      if (missing.length) { toast('请先填写：' + missing.join('、'), 'error'); return; }
      try {
        const costs = this.feeRows.filter(r => r.equipment_id).map(r => ({
          equipment_id: r.equipment_id, test_item: r.test_item,
          test_time: Number(r.test_time) || 0, test_count: Number(r.test_count) || 1,
          quantity: Number(r.quantity) || 1, discount: Number(r.discount) || 1,
          service_fee: Number(r.service_fee) || 0,
        }));
        await api('/api/review/' + this.current.id, 'POST', { approve: true, reviewer_id: this.detail.reviewer_id || null, costs });
        toast('审核通过', 'success'); this.showModal = false; this.load();
      } catch (e) { toast(e.message, 'error'); }
    },
    async reject() {
      if (!this.rejectReason || !this.rejectReason.trim()) {
        toast('请填写否决原因后再否决', 'error'); return;
      }
      try {
        await api('/api/review/' + this.current.id, 'POST', { approve: false, reject_reason: this.rejectReason.trim() });
        toast('已否决', 'success'); this.showModal = false; this.load();
      } catch (e) { toast(e.message, 'error'); }
    },
    badge,
  },
  mounted() { this.load(); },
  template: `
  <div class="card">
    <h3>委托审核</h3>
    <table class="tbl"><thead><tr><th>委托编号</th><th>委托单位</th><th>委托人</th><th>检测项目</th><th>委托时间</th><th>操作</th></tr></thead>
    <tbody>
      <tr v-for="o in list" :key="o.id">
        <td>{{o.order_no}}</td><td>{{o.entrust_org}}</td><td>{{o.entruster}}</td>
        <td>{{o.test_item}}</td><td>{{fmtD(o.created_at)}}</td>
        <td><button class="btn primary sm" @click="open(o)">审核</button></td>
      </tr>
      <tr v-if="!list.length"><td colspan="6" class="empty">暂无待审核委托</td></tr>
    </tbody></table>
  </div>
  <div class="modal-mask" v-if="showModal" @click.self="showModal=false">
    <div class="modal" style="width:1240px">
      <h3>审核委托申请</h3>
      <div v-if="detail">
        <table class="tbl"><tbody>
          <tr><td style="width:100px" class="lbl">委托单位</td><td>{{detail.entrust_org}}</td><td style="width:80px" class="lbl">委托人</td><td>{{detail.entruster}}</td></tr>
          <tr><td class="lbl">样品</td><td>{{detail.sample_model}} ×{{detail.sample_count}}{{detail.sample_unit}}</td><td class="lbl">检测项目</td><td>{{detail.test_item}}</td></tr>
          <tr><td class="lbl">检测依据</td><td colspan="3">{{detail.test_basis || '客户自定义条件'}}</td></tr>
          <tr v-if="detail.test_condition"><td class="lbl">试验条件</td><td colspan="3" style="white-space:pre-wrap">{{detail.test_condition}}</td></tr>
          <tr v-if="detail.images && detail.images.length"><td class="lbl">试验条件附图</td><td colspan="3"><div class="img-thumbs"><a v-for="im in detail.images" :key="im.id" :href="im.path" target="_blank" :title="im.filename"><img :src="im.path" :alt="im.filename"></a></div></td></tr>
          <tr v-if="detail.criteria"><td class="lbl">判定标准</td><td colspan="3" style="white-space:pre-wrap">{{detail.criteria}}</td></tr>
          <tr v-if="detail.case_images && detail.case_images.length"><td class="lbl">用例图片</td><td colspan="3"><div class="img-thumbs"><a v-for="im in detail.case_images" :key="im.id" :href="im.path" target="_blank" :title="im.filename"><img :src="im.path" :alt="im.filename"></a></div></td></tr>
          <tr><td class="lbl">联系电话</td><td>{{detail.phone}}</td><td class="lbl">要求时间</td><td>{{fmtDT(detail.required_start)}}</td></tr>
        </tbody></table>

        <h4 style="margin:14px 0 8px"><span style="color:#c62828">*</span>实验员</h4>
        <div class="form-group"><select v-model="detail.reviewer_id">
          <option :value="null">请选择实验员</option>
          <option v-for="r in reviewers" :value="r.id">{{r.name}}（{{roleText(r.role)}}）</option>
        </select></div>

        <h4 style="margin:14px 0 8px"><span style="color:#c62828">*</span>费用明细（选择设备自动带出计价）</h4>
        <div style="overflow-x:auto">
        <table class="tbl"><thead><tr><th>试验项目</th><th>设备</th><th>开机费</th><th>电费/小时</th><th>设备折旧/小时</th><th>耗材费用/小时</th><th>测试时间</th><th>测试次数</th><th>数量</th><th>折扣</th><th>服务费用</th><th>测试费用（元）</th><th></th></tr></thead>
        <tbody>
          <tr v-for="(r,i) in feeRows" :key="i">
            <td><input v-model="r.test_item" style="width:100%;padding:4px"></td>
            <td><select v-model="r.equipment_id" @change="onEqChange(r)" style="width:100%;padding:4px"><option :value="null">选择设备</option>
              <option v-for="e in allEq" :value="e.id">{{e.name}}</option></select></td>
            <td>{{r.open_fee}}</td><td>{{r.power_fee}}</td><td>{{r.depreciation_fee}}</td><td>{{r.consumable_fee}}</td>
            <td><input type="number" v-model.number="r.test_time" style="width:64px;padding:4px"></td>
            <td><input type="number" v-model.number="r.test_count" style="width:64px;padding:4px"></td>
            <td><input type="number" v-model.number="r.quantity" style="width:64px;padding:4px"></td>
            <td><input type="number" step="0.1" v-model.number="r.discount" style="width:64px;padding:4px"></td>
            <td><input type="number" v-model.number="r.service_fee" style="width:72px;padding:4px"></td>
            <td style="font-weight:600">{{rowAmount(r)}}</td>
            <td><button class="btn link" @click="feeRows.splice(i,1)">删除</button></td>
          </tr>
        </tbody></table>
        </div>
        <button class="btn sm" style="margin-top:8px" @click="addFee">+ 添加费用项</button>

        <div class="form-group" style="margin-top:14px"><label>否决原因（否决时填写）</label><textarea v-model="rejectReason"></textarea></div>
      </div>
      <div class="modal-actions">
        <button class="btn danger" :disabled="!rejectReason || !rejectReason.trim()" @click="reject">否决</button>
        <button class="btn" @click="showModal=false">取消</button>
        <button class="btn success" @click="approve">通过</button>
      </div>
    </div>
  </div>`,
};

/* ---------------- 样品池二维码标签打印 ---------------- */
function printBatchSampleLabels(batch, samples) {
  const base = location.origin;
  const labels = samples.map(s => `
    <div class="label">
      <img class="qr" src="${base}/q/${s.id}/qr.png" alt="二维码">
      <div class="line">批次号：${escHtml(batch.batch_no)}</div>
      <div class="line">状况：${escHtml(s.condition || '-')}</div>
      <div class="line">样品编号：${escHtml(s.sample_no)}</div>
    </div>`).join('');
  const w = window.open('', '_blank', 'width=760,height=820');
  w.document.write(`<html><head><meta charset="utf-8"><title>样品条码标签</title><style>
    body{font-family:'Microsoft YaHei',Arial,sans-serif;padding:24px}
    .labels{display:flex;flex-wrap:wrap;gap:14px}
    .label{border:1px solid #000;padding:14px;width:220px;text-align:center;page-break-inside:avoid}
    .qr{width:180px;height:180px;display:block;margin:0 auto 10px}
    .line{font-size:13px;margin-top:4px;font-weight:600}
    @media print{body{padding:0}}
  </style></head><body>
    <div class="labels">${labels}</div>
    <script>window.onload=function(){window.print()};<\/script></body></html>`);
  w.document.close();
}

/* ---------------- 样品管理（样品池） ---------------- */
const SamplesView = {
  data: () => ({
    batches: [],
    // 样品池
    showBatchForm: false,
    batchForm: { entrust_org: '', entruster: '', sample_name: '', sample_model: '', customer_model: '', sample_stage: '', unit: '台', sn_text: '', remark: '' },
    expanded: {},
    batchQuery: { batch_no: '', sn: '', sample_model: '', date_from: '', date_to: '' },
    sampleDetail: null, showSampleDetail: false,
    showSampleEdit: false, editId: null, editForm: { sn: '', status: '', condition: '' },
    sampleStatuses: ['待接收', '已接收', '已排期', '实验中', '已完成', '已退还', '已报废', '已留存'],
    sampleStages: ['EVT', 'DVT', 'DVT-2', 'DVT-3', 'PVT', 'PVT-2', 'PVT-3', 'MP', '二供', '三供', '四供', '五供'],
    showPrint: false, printBatch: null, printSampleId: null,
  }),
  methods: {
    async load() { this.loadBatches(); },
    async loadBatches() { this.batches = await api('/api/samples/batches'); },
    // ---- 样品池 ----
    openBatchForm() { this.batchForm = { entrust_org: '', entruster: '', sample_name: '', sample_model: '', customer_model: '', sample_stage: '', unit: '台', sn_text: '', remark: '' }; this.showBatchForm = true; },
    async createBatch() {
      try {
        const sn_list = this.batchForm.sn_text.split(/[\n\r,，;；\s]+/).map(s => s.trim()).filter(Boolean);
        if (!sn_list.length) { toast('请粘贴 SN 列表', 'error'); return; }
        const { sn_text, ...payload } = this.batchForm;
        await api('/api/samples/batches', 'POST', { ...payload, sn_list });
        this.showBatchForm = false; this.loadBatches(); toast('批次已录入', 'success');
      } catch (e) { toast(e.message, 'error'); }
    },
    toggleBatch(b) { this.expanded[b.id] = !this.expanded[b.id]; },
    async confirmBatch(b) {
      const c = prompt('确认状况（默认：样品正常）', '样品正常');
      if (c === null) return; // 用户取消，不确认
      try { await api('/api/samples/batches/' + b.id + '/confirm', 'POST', { condition: c.trim() || '样品正常' }); this.loadBatches(); toast('整批已确认', 'success'); }
      catch (e) { toast(e.message, 'error'); }
    },
    async disposeBatch(b, action) {
      const r = prompt('备注', '');
      if (r === null) return; // 用户取消，不处置
      try { await api('/api/samples/batches/' + b.id + '/dispose', 'POST', { action, remark: r.trim() }); this.loadBatches(); toast('整批已' + action, 'success'); }
      catch (e) { toast(e.message, 'error'); }
    },
    async confirmSample(s) {
      const c = prompt('确认状况（默认：样品正常）', '样品正常');
      if (c === null) return; // 用户取消，不确认
      try { await api('/api/samples/' + s.id + '/receive', 'POST', { condition: c.trim() || '样品正常' }); this.loadBatches(); toast('已确认', 'success'); }
      catch (e) { toast(e.message, 'error'); }
    },
    async disposeSample(s, action) {
      const r = prompt('备注', '');
      if (r === null) return; // 用户取消，不处置
      try { await api('/api/samples/' + s.id + '/dispose', 'POST', { action, remark: r.trim() }); this.loadBatches(); toast('已' + action, 'success'); }
      catch (e) { toast(e.message, 'error'); }
    },
    openSampleEdit(s) {
      this.editId = s.id;
      this.editForm = { sn: s.sn || '', status: s.status, condition: s.condition || '' };
      this.showSampleEdit = true;
    },
    async saveSampleEdit() {
      try {
        await api('/api/samples/' + this.editId + '/update', 'POST', { ...this.editForm });
        this.showSampleEdit = false; this.loadBatches(); toast('已保存', 'success');
      } catch (e) { toast(e.message, 'error'); }
    },
    async openSampleDetail(s) {
      try {
        this.sampleDetail = await api('/api/samples/' + s.id + '/history');
        this.showSampleDetail = true;
      } catch (e) { toast(e.message, 'error'); }
    },
    batchStatus(b) {
      const samples = b.samples || [];
      const wait = samples.filter(s => s.status === '待接收').length;
      const ok = samples.filter(s => s.status === '已接收').length;
      const done = samples.filter(s => ['已退还', '已报废', '已留存'].includes(s.status)).length;
      return `待确认 ${wait} · 已确认 ${ok} · 已处置 ${done}`;
    },
    resetBatchQuery() { this.batchQuery = { batch_no: '', sn: '', sample_model: '', date_from: '', date_to: '' }; },
    openPrint(b) { this.printBatch = b; this.printSampleId = null; this.showPrint = true; },
    printBatchAll() { printBatchSampleLabels(this.printBatch, this.printBatch.samples); this.showPrint = false; },
    printSingle() {
      const s = (this.printBatch.samples || []).find(x => x.id === this.printSampleId);
      if (!s) { toast('请选择要打印的样品', 'error'); return; }
      printBatchSampleLabels(this.printBatch, [s]);
      this.showPrint = false;
    },
    badge, fmtDT,
  },
  computed: {
    filteredBatches() {
      const q = this.batchQuery;
      return this.batches.filter(b => {
        if (q.batch_no && !(b.batch_no || '').toLowerCase().includes(q.batch_no.toLowerCase())) return false;
        if (q.sample_model && !(b.sample_model || '').toLowerCase().includes(q.sample_model.toLowerCase())) return false;
        if (q.sn && !(b.samples || []).some(s => (s.sn || '').toLowerCase().includes(q.sn.toLowerCase()))) return false;
        const day = (b.created_at || '').slice(0, 10);
        if (q.date_from && day < q.date_from) return false;
        if (q.date_to && day > q.date_to) return false;
        return true;
      });
    },
  },
  mounted() { this.load(); },
  template: `
  <div class="card">
    <h3>样品管理</h3>

    <!-- 样品池 -->
    <div>
      <div class="toolbar" style="margin-top:12px">
        <button class="btn primary" @click="openBatchForm">＋ 新建批次（批量录 SN）</button>
        <span style="margin-left:auto;color:var(--muted);font-size:13px">样品查询：</span>
        <input v-model="batchQuery.batch_no" placeholder="批次号" style="width:130px">
        <input v-model="batchQuery.sn" placeholder="SN 号" style="width:140px">
        <input v-model="batchQuery.sample_model" placeholder="DHD型号" style="width:130px">
        <input type="date" v-model="batchQuery.date_from" title="录入日期从" style="width:150px">
        <span style="color:var(--muted)">至</span>
        <input type="date" v-model="batchQuery.date_to" title="录入日期至" style="width:150px">
        <button class="btn sm" @click="resetBatchQuery">重置</button>
      </div>
      <table class="tbl"><thead><tr><th>批次号</th><th>来源单位</th><th>样品名称</th><th>型号</th><th>样品阶段</th><th>数量</th><th>录入人</th><th>录入时间</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>
          <template v-for="b in filteredBatches" :key="b.id">
            <tr @click="toggleBatch(b)" style="cursor:pointer">
              <td>{{b.batch_no}}</td>
              <td>{{b.entrust_org||'-'}}<div v-if="b.entruster" style="font-size:12px;color:var(--muted)">委托人：{{b.entruster}}</div></td>
              <td>{{b.sample_name||'-'}}</td>
              <td>{{b.sample_model||'-'}}</td>
              <td>{{b.sample_stage||'-'}}</td>
              <td>{{b.quantity}}{{b.unit}}</td>
              <td>{{b.operator}}</td>
              <td>{{fmtDT(b.created_at)}}</td>
              <td style="font-size:12px;color:var(--muted)">{{batchStatus(b)}}</td>
              <td><button class="btn sm" @click.stop="toggleBatch(b)">{{expanded[b.id] ? '收起 ▲' : '展开 ▼'}}</button></td>
            </tr>
            <tr v-if="expanded[b.id]">
              <td colspan="10" style="background:#f7f9fc;padding:12px">
                <div style="margin-bottom:8px">
                  <button class="btn success sm" @click="confirmBatch(b)">整批确认</button>
                  <button class="btn sm" @click="disposeBatch(b,'退还')">整批退还</button>
                  <button class="btn sm" @click="disposeBatch(b,'报废')">整批报废</button>
                  <button class="btn sm" @click="disposeBatch(b,'留存')">整批留存</button>
                  <button class="btn sm" @click="openPrint(b)">打印条码</button>
                </div>
                <table class="tbl"><thead><tr><th>SN</th><th>样品编号</th><th>状态</th><th>状况</th><th>结果</th><th>备注</th><th>操作</th></tr></thead>
                  <tbody>
                    <tr v-for="s in b.samples" :key="s.id">
                      <td>{{s.sn||'-'}}</td>
                      <td>{{s.sample_no}}</td>
                      <td v-html="badge(s.status, {'待接收':'gray','已接收':'blue','已排期':'purple','实验中':'orange','已完成':'green','已退还':'gray','已报废':'red','已留存':'green'})"></td>
                      <td>{{s.condition}}</td>
                      <td>{{s.result||'-'}}</td>
                      <td>{{s.remark}}</td>
                      <td>
                        <button class="btn success sm" v-if="s.status==='待接收'" @click="confirmSample(s)">确认</button>
                        <button class="btn sm" v-if="['已完成','实验中','已接收'].includes(s.status)" @click="disposeSample(s,'退还')">退还</button>
                        <button class="btn sm" v-if="['已完成','实验中','已接收'].includes(s.status)" @click="disposeSample(s,'报废')">报废</button>
                        <button class="btn sm" v-if="['已完成','实验中','已接收'].includes(s.status)" @click="disposeSample(s,'留存')">留存</button>
                        <button class="btn link sm" @click="openSampleEdit(s)">编辑</button>
                        <button class="btn link sm" @click="openSampleDetail(s)">明细</button>
                      </td>
                    </tr>
                    <tr v-if="!b.samples.length"><td colspan="7" class="empty">暂无样品</td></tr>
                  </tbody></table>
              </td>
            </tr>
          </template>
          <tr v-if="!filteredBatches.length"><td colspan="10" class="empty">{{ batches.length ? '没有符合查询条件的批次' : '暂无批次，点击上方「新建批次」录入' }}</td></tr>
        </tbody></table>
    </div>
  </div>

  <!-- 新建批次 -->
  <div class="modal-mask" v-if="showBatchForm" @click.self="showBatchForm=false">
    <div class="modal" style="width:640px">
      <h3>新建样品批次</h3>
      <div class="form-row">
        <div class="form-group"><label>来源委托单位</label><input v-model="batchForm.entrust_org"></div>
        <div class="form-group"><label>委托人</label><input v-model="batchForm.entruster"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>样品名称</label><input v-model="batchForm.sample_name"></div>
        <div class="form-group"><label>DHD型号</label><input v-model="batchForm.sample_model"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>客户型号</label><input v-model="batchForm.customer_model"></div>
        <div class="form-group"><label>样品阶段</label><input v-model="batchForm.sample_stage" list="sampleStageOptions" placeholder="如 EVT / DVT / PVT"><datalist id="sampleStageOptions"><option v-for="st in sampleStages" :key="st" :value="st"></option></datalist></div>
        <div class="form-group" style="flex:0 0 90px"><label>单位</label><input v-model="batchForm.unit"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>备注</label><input v-model="batchForm.remark"></div>
      </div>
      <div class="form-group">
        <label>SN 列表（每行一个，或逗号/空格分隔）</label>
        <textarea v-model="batchForm.sn_text" rows="6" placeholder="粘贴 SN，每行一个，如：&#10;SN20260828001&#10;SN20260828002"></textarea>
      </div>
      <div class="modal-actions">
        <button class="btn" @click="showBatchForm=false">取消</button>
        <button class="btn primary" @click="createBatch">录入批次</button>
      </div>
    </div>
  </div>

  <!-- 样品编辑 -->
  <div class="modal-mask" v-if="showSampleEdit" @click.self="showSampleEdit=false">
    <div class="modal" style="width:480px">
      <h3>编辑样品</h3>
      <div class="form-group"><label>SN</label><input v-model="editForm.sn" placeholder="SN 序列号"></div>
      <div class="form-group"><label>状态</label><select v-model="editForm.status">
        <option v-for="st in sampleStatuses" :key="st" :value="st">{{st}}</option>
      </select></div>
      <div class="form-group"><label>状况</label><input v-model="editForm.condition" placeholder="如：样品正常"></div>
      <div class="modal-actions">
        <button class="btn" @click="showSampleEdit=false">取消</button>
        <button class="btn primary" @click="saveSampleEdit">保存</button>
      </div>
    </div>
  </div>

  <!-- 样品明细 -->
  <div class="modal-mask" v-if="showSampleDetail && sampleDetail" @click.self="showSampleDetail=false">
    <div class="modal" style="width:960px">
      <h3>样品明细 —— {{sampleDetail.sample_no}}</h3>
      <div style="color:var(--muted);font-size:12px;margin-bottom:14px">
        SN {{sampleDetail.sn||'-'}} · 批次 {{sampleDetail.batch_no||'无'}} · 状态 <span v-html="badge(sampleDetail.status, {'待接收':'gray','已接收':'blue','已排期':'purple','实验中':'orange','已完成':'green','已退还':'gray','已报废':'red','已留存':'green'})"></span>
      </div>

      <div style="margin-bottom:16px">
        <div style="font-weight:600;margin-bottom:6px">关联委托单 / 测试位结果（由排期关联，支持样机复用）</div>
        <table class="tbl"><thead><tr><th>实验编号/委托单</th><th>委托单位</th><th>检测项目</th><th>结果</th></tr></thead>
          <tbody>
            <tr v-for="sc in sampleDetail.schedules" :key="sc.id">
              <td>{{sc.order_no||'-'}}</td>
              <td>{{sc.entrust_org||'-'}}</td>
              <td>{{sc.test_item||'-'}}</td>
              <td>{{sc.result||'-'}}</td>
            </tr>
            <tr v-if="!sampleDetail.schedules.length"><td colspan="4" class="empty">暂无关联委托单</td></tr>
          </tbody></table>
      </div>

      <div style="margin-bottom:16px">
        <div style="font-weight:600;margin-bottom:6px">实验信息（排期）</div>
        <table class="tbl"><thead><tr><th>设备</th><th>实验用时(h)</th><th>过渡用时(h)</th><th>总用时(h)</th><th>预计开始</th><th>预计结束</th><th>实际开始</th><th>实际结束</th><th>状态</th></tr></thead>
          <tbody>
            <tr v-for="sc in sampleDetail.schedules" :key="sc.id">
              <td>{{sc.equipment_name}}</td>
              <td>{{sc.experiment_hours}}</td>
              <td>{{sc.transition_hours}}</td>
              <td>{{sc.total_hours}}</td>
              <td>{{fmtDT(sc.plan_start)}}</td>
              <td>{{fmtDT(sc.plan_end)}}</td>
              <td>{{fmtDT(sc.actual_start)}}</td>
              <td>{{fmtDT(sc.actual_end)}}</td>
              <td v-html="badge(sc.status)"></td>
            </tr>
            <tr v-if="!sampleDetail.schedules.length"><td colspan="9" class="empty">暂无实验排期</td></tr>
          </tbody></table>
      </div>

      <div>
        <div style="font-weight:600;margin-bottom:6px">操作记录（全部变动）</div>
        <table class="tbl"><thead><tr><th>时间</th><th>操作</th><th>操作人</th><th>备注</th></tr></thead>
          <tbody>
            <tr v-for="op in sampleDetail.operations" :key="op.id">
              <td>{{fmtDT(op.created_at)}}</td>
              <td>{{op.action}}</td>
              <td>{{op.operator}}</td>
              <td>{{op.remark}}</td>
            </tr>
            <tr v-if="!sampleDetail.operations.length"><td colspan="4" class="empty">暂无操作记录</td></tr>
          </tbody></table>
      </div>

      <div class="modal-actions"><button class="btn" @click="showSampleDetail=false">关闭</button></div>
    </div>
  </div>

  <!-- 打印条码 -->
  <div class="modal-mask" v-if="showPrint && printBatch" @click.self="showPrint=false">
    <div class="modal" style="width:480px">
      <h3>打印条码 —— {{printBatch.batch_no}}</h3>
      <p style="color:var(--muted);font-size:12px;margin:0 0 14px">共 {{printBatch.samples.length}} 台样品，可批量打印或选择单台打印。</p>
      <div style="margin-bottom:12px">
        <button class="btn primary" @click="printBatchAll">批量打印（全部 {{printBatch.samples.length}} 台）</button>
      </div>
      <div class="form-group">
        <label>单台打印</label>
        <select v-model="printSampleId">
          <option :value="null" disabled>请选择样品</option>
          <option v-for="s in printBatch.samples" :key="s.id" :value="s.id">{{s.sample_no}} · SN {{s.sn||'-'}}</option>
        </select>
      </div>
      <div class="modal-actions">
        <button class="btn" @click="showPrint=false">取消</button>
        <button class="btn primary" @click="printSingle">单台打印</button>
      </div>
    </div>
  </div>

  `,
};

/* ---------------- 实验排期 ---------------- */
const ScheduleView = {
  data: () => ({ orders: [], cur: null, detail: null, eq: [], batches: [], curBatchId: null, experimenters: [], showModal: false, form: { sample_ids: [], equipment_id: null, experiment_hours: 4, transition_hours: 0, plan_start: '', experimenter_id: null } }),
  computed: {
    needCount() { return this.detail ? (this.detail.sample_count || 0) : 0; },
    scheduledCount() { return (this.detail && this.detail.schedules) ? this.detail.schedules.length : 0; },
    full() { return this.scheduledCount >= this.needCount; },
    curBatch() { return this.batches.find(b => b.id === this.curBatchId) || null; },
  },
  methods: {
    async load() {
      this.orders = await api('/api/orders?status=');
      this.eq = await api('/api/equipment');
      this.experimenters = (await api('/api/auth/users')).filter(u => u.role !== 'entruster');
    },
    async open(o) {
      this.cur = o;
      this.detail = await api('/api/orders/' + o.id);
      this.batches = (await api('/api/samples/batches'))
        .map(b => {
          b.ok = (b.samples || []).filter(s => this.canPick(s)).length;
          return b;
        })
        .filter(b => b.ok > 0);
      this.curBatchId = this.batches.length ? this.batches[0].id : null;
      // 实验员默认带出审核时指定的实验员，可修改
      this.form = { sample_ids: [], equipment_id: null, experiment_hours: 4, transition_hours: 0, plan_start: '', experimenter_id: this.detail.reviewer_id || null };
      this.showModal = true;
    },
    canPick(s) { return !s.order_id && ['已接收','已排期','实验中','已完成'].includes(s.status) && !this.scheduledFor(s); },
    scheduledFor(s) { return !!(this.detail && this.detail.schedules && this.detail.schedules.some(sc => sc.sample_id === s.id)); },
    curSamples() { return this.curBatch ? [...this.curBatch.samples].sort((a, b) => (this.canPick(a) === this.canPick(b)) ? 0 : (this.canPick(a) ? -1 : 1)) : []; },
    async addSchedule() {
      try {
        if (!this.form.sample_ids.length) { toast('请选择样品', 'error'); return; }
        if (!this.form.equipment_id) { toast('请选择设备', 'error'); return; }
        if (!this.form.plan_start) { toast('预计开始时间必填', 'error'); return; }
        const remain = this.needCount - this.scheduledCount;
        if (this.form.sample_ids.length > remain) { toast('已选 ' + this.form.sample_ids.length + ' 台，但还可再排 ' + remain + ' 条', 'error'); return; }
        for (const sid of this.form.sample_ids) {
          await api('/api/schedules', 'POST', {
            sample_id: sid,
            order_id: this.cur.id,
            equipment_id: this.form.equipment_id,
            experiment_hours: Number(this.form.experiment_hours),
            transition_hours: Number(this.form.transition_hours),
            plan_start: this.form.plan_start || null,
            experimenter_id: this.form.experimenter_id || null,
          });
        }
        toast('已生成 ' + this.form.sample_ids.length + ' 条排期计划', 'success'); this.open(this.cur);
      } catch (e) { toast(e.message, 'error'); }
    },
    async removeSchedule(s) {
      if (!confirm('确定删除这条排期计划？')) return;
      try { await api('/api/schedules/' + s.id, 'DELETE'); toast('已删除', 'success'); this.open(this.cur); }
      catch (e) { toast(e.message, 'error'); }
    },
    badge, fmtDT,
  },
  mounted() { this.load(); },
  template: `
  <div class="card">
    <h3>实验排期</h3>
    <table class="tbl"><thead><tr><th>实验编号</th><th>委托单位</th><th>委托人</th><th>DHD型号</th><th>检测项目</th><th>需求数量</th><th>状态</th><th>操作</th></tr></thead>
    <tbody>
      <template v-for="o in orders" :key="o.id">
        <tr v-if="['已审核','已排期','实验中'].includes(o.status)">
          <td>{{o.experiment_no||o.order_no}}</td><td>{{o.entrust_org}}</td><td>{{o.entruster||'-'}}</td><td>{{o.sample_model||'-'}}</td><td>{{o.test_item}}</td>
          <td>{{o.sample_count}} {{o.sample_unit}}</td>
          <td v-html="badge(o.status)"></td><td><button class="btn primary sm" @click="open(o)">排期</button></td>
        </tr>
      </template>
    </tbody></table>
  </div>
  <div class="modal-mask" v-if="showModal" @click.self="showModal=false">
    <div class="modal" style="width:920px">
      <h3>样品排期计划 —— {{cur.experiment_no||cur.order_no}}</h3>
      <div style="color:var(--muted);font-size:13px;margin:4px 0 10px">
        委托单位 {{detail.entrust_org||'-'}} · 检测项目 {{detail.test_item||'-'}} · 需求数量 <b>{{needCount}}</b> {{detail.sample_unit||''}} · 已排 <b>{{scheduledCount}}</b>/{{needCount}}
        <span v-if="full" style="color:#0a7d32;font-weight:600">（已排满）</span>
        <span v-else style="color:#b26a00">（还可再排 {{needCount - scheduledCount}} 条）</span>
      </div>

      <div style="font-weight:600;margin:2px 0 6px">选择样品<span style="color:var(--muted);font-weight:400;margin-left:8px">可多选 · 可复用 · 已选 {{form.sample_ids.length}} 台</span></div>

      <div style="color:var(--muted);font-size:12px;margin:2px 0 4px">① 选择样品批次</div>
      <div style="max-height:140px;overflow:auto;border:1px solid var(--border);border-radius:4px">
        <table class="tbl" style="margin:0">
          <thead><tr>
            <th style="position:sticky;top:0;width:34px"></th>
            <th style="position:sticky;top:0">批次号</th>
            <th style="position:sticky;top:0">来源单位</th>
            <th style="position:sticky;top:0">样品名称</th>
            <th style="position:sticky;top:0">型号</th>
            <th style="position:sticky;top:0">样品阶段</th>
            <th style="position:sticky;top:0">数量</th>
            <th style="position:sticky;top:0">可排</th>
          </tr></thead>
          <tbody>
            <tr v-for="b in batches" :key="b.id" @click="curBatchId=b.id" style="cursor:pointer" :style="curBatchId===b.id ? 'background:#eef4ff' : ''">
              <td><input type="radio" :value="b.id" v-model="curBatchId" @click.stop></td>
              <td>{{b.batch_no}}</td>
              <td>{{b.entrust_org||'-'}}</td>
              <td>{{b.sample_name||'-'}}</td>
              <td>{{b.sample_model||'-'}}</td>
              <td>{{b.sample_stage||'-'}}</td>
              <td>{{b.quantity}}{{b.unit||''}}</td>
              <td>{{b.ok}} 台</td>
            </tr>
            <tr v-if="!batches.length"><td colspan="8" class="empty">暂无可排期的样品批次（需已接收/已排期/实验中/已完成样机），请先到「样品管理」新建批次并确认</td></tr>
          </tbody>
        </table>
      </div>

      <div style="color:var(--muted);font-size:12px;margin:8px 0 4px">② 勾选样机<span v-if="curBatch">（{{curBatch.batch_no}}）</span><span style="margin-left:8px">灰色 = 已绑单 / 状态不可排 / 已排本单</span></div>
      <div style="max-height:170px;overflow:auto;border:1px solid var(--border);border-radius:4px">
        <table class="tbl" style="margin:0">
          <thead><tr><th style="position:sticky;top:0;width:40px"></th><th style="position:sticky;top:0">SN</th><th style="position:sticky;top:0">样品编号</th><th style="position:sticky;top:0">状态</th></tr></thead>
          <tbody>
            <tr v-for="s in curSamples()" :key="s.id">
              <td><input type="checkbox" :value="s.id" v-model="form.sample_ids" :disabled="!canPick(s)"></td>
              <td>{{s.sn||'-'}}</td>
              <td>{{s.sample_no}}</td>
              <td><span v-html="badge(s.status, {'待接收':'gray','已接收':'blue','已排期':'purple','实验中':'orange','已完成':'green','已退还':'gray','已报废':'red','已留存':'green'})"></span><span v-if="scheduledFor(s)" style="color:var(--muted);font-size:12px;margin-left:6px;border:1px solid var(--border);border-radius:3px;padding:0 4px">已排本单</span></td>
            </tr>
            <tr v-if="!curBatch"><td colspan="4" class="empty">请先在上方选择一个样品批次</td></tr>
          </tbody>
        </table>
      </div>

      <div class="form-row" style="background:#f7f9fc;padding:12px;border-radius:6px;margin-top:12px">
        <div class="form-group" style="flex:0 0 260px;margin-bottom:0"><label>实验员</label><select v-model="form.experimenter_id">
          <option :value="null">默认（同审核时实验员）</option>
          <option v-for="u in experimenters" :value="u.id">{{u.name}}（{{roleText(u.role)}}）</option>
        </select></div>
        <div style="color:var(--muted);font-size:12px;align-self:flex-end;padding-bottom:8px">默认带出审核时指定的实验员，可修改</div>
      </div>

      <div class="form-row" style="background:#f7f9fc;padding:12px;border-radius:6px;margin-top:12px">
        <div class="form-group" style="flex:1 1 180px;margin-bottom:0"><label>设备</label><select v-model="form.equipment_id">
          <option :value="null">选择设备</option>
          <option v-for="e in eq" :value="e.id" :disabled="['停用','报废'].includes(e.status)">{{e.name}}（{{e.exp_type}}）</option>
        </select></div>
        <div class="form-group" style="flex:0 0 90px;margin-bottom:0"><label>实验用时(h)</label><input type="number" v-model.number="form.experiment_hours"></div>
        <div class="form-group" style="flex:0 0 90px;margin-bottom:0"><label>过渡用时(h)</label><input type="number" v-model.number="form.transition_hours"></div>
        <div class="form-group" style="flex:0 0 215px;margin-bottom:0"><label>预计开始时间 <span class="req">*</span></label><input type="datetime-local" v-model="form.plan_start"></div>
        <div class="form-group" style="flex:0 0 auto;margin-bottom:0;align-self:flex-end"><button class="btn primary" :disabled="full" @click="addSchedule">生成排期计划</button></div>
      </div>

      <div style="font-weight:600;margin:14px 0 6px">已生成排期计划</div>
      <table class="tbl"><thead><tr><th>SN</th><th>样品编号</th><th>设备</th><th>实验员</th><th>总用时</th><th>预计开始</th><th>结果</th><th>状态</th><th>操作</th></tr></thead>
      <tbody>
        <tr v-for="s in detail.schedules" :key="s.id">
          <td>{{s.sn||'-'}}</td><td>{{s.sample_no}}</td><td>{{s.equipment_name}}</td>
          <td>{{s.experimenter_name||'-'}}</td>
          <td>{{s.total_hours}}</td><td>{{fmtDT(s.plan_start)}}</td><td>{{s.result||'-'}}</td><td v-html="badge(s.status)"></td>
          <td><button class="btn link sm" v-if="s.status==='已排期'" @click="removeSchedule(s)">删除</button></td>
        </tr>
        <tr v-if="!detail.schedules.length"><td colspan="9" class="empty">暂无排期计划，请在上方选择样品并填写排期信息后生成</td></tr>
      </tbody></table>
      <div class="modal-actions"><button class="btn" @click="showModal=false">关闭</button></div>
    </div>
  </div>`,
};

/* ---------------- 实验开始 ---------------- */
const ExperimentStartView = {
  data: () => ({ orders: [], cur: null, detail: null, showModal: false, startTarget: null, startForm: { experimenter_id: null, equipment_id: null, experiment_hours: 4 }, experimenters: [], eq: [] }),
  methods: {
    async load() {
      this.orders = await api('/api/orders?status=');
      this.experimenters = (await api('/api/auth/users')).filter(u => u.role !== 'entruster');
      this.eq = await api('/api/equipment');
    },
    async open(o) { this.cur = o; this.detail = await api('/api/orders/' + o.id); this.showModal = true; },
    openStart(s) {
      // 开始前确认：实验员/设备默认带出排期信息，可修改；预算实验时长默认排期实验用时
      this.startTarget = s;
      this.startForm = { experimenter_id: s.experimenter_id || null, equipment_id: s.equipment_id, experiment_hours: s.experiment_hours };
    },
    async confirmStart() {
      try {
        if (!this.startForm.equipment_id) { toast('请选择设备', 'error'); return; }
        if (!(this.startForm.experiment_hours > 0)) { toast('预算实验时长必须大于 0', 'error'); return; }
        await api('/api/experiment/schedule/' + this.startTarget.id + '/start', 'POST', {
          experimenter_id: this.startForm.experimenter_id || null,
          equipment_id: this.startForm.equipment_id,
          experiment_hours: Number(this.startForm.experiment_hours),
        });
        this.startTarget = null; this.open(this.cur); toast('实验已开始', 'success');
      } catch (e) { toast(e.message, 'error'); }
    },
    badge, fmtDT,
  },
  mounted() { this.load(); },
  template: `
  <div class="card">
    <h3>实验开始</h3>
    <table class="tbl"><thead><tr><th>实验编号</th><th>委托单位</th><th>检测项目</th><th>状态</th><th>操作</th></tr></thead>
    <tbody>
      <template v-for="o in orders" :key="o.id">
        <tr v-if="['已排期','实验中'].includes(o.status)">
          <td>{{o.experiment_no||o.order_no}}</td><td>{{o.entrust_org}}</td><td>{{o.test_item}}</td>
          <td v-html="badge(o.status)"></td><td><button class="btn primary sm" @click="open(o)">开始实验</button></td>
        </tr>
      </template>
    </tbody></table>
  </div>
  <div class="modal-mask" v-if="showModal" @click.self="showModal=false">
    <div class="modal" style="width:960px">
      <h3>实验开始 —— {{cur.experiment_no||cur.order_no}}</h3>
      <h4 style="margin:10px 0 6px">排期计划</h4>
      <table class="tbl"><thead><tr><th>SN</th><th>样品编号</th><th>设备</th><th>实验员</th><th>状态</th><th>预计开始</th><th>操作</th></tr></thead>
      <tbody>
        <tr v-for="s in detail.schedules" :key="s.id">
          <td>{{s.sn||'-'}}</td><td>{{s.sample_no}}</td><td>{{s.equipment_name}}</td><td>{{s.experimenter_name||'-'}}</td>
          <td v-html="badge(s.status)"></td><td>{{fmtDT(s.plan_start)}}</td>
          <td><button class="btn success sm" v-if="s.status==='已排期'" @click="openStart(s)">开始</button></td>
        </tr>
        <tr v-if="!detail.schedules.length"><td colspan="7" class="empty">暂无排期</td></tr>
      </tbody></table>
      <div class="modal-actions"><button class="btn" @click="showModal=false">关闭</button></div>
    </div>
  </div>
  <div class="modal-mask" v-if="startTarget" @click.self="startTarget=null">
    <div class="modal" style="width:480px">
      <h3>开始实验 —— {{startTarget.sample_no}}</h3>
      <div class="form-group"><label>实验员</label><select v-model="startForm.experimenter_id">
        <option :value="null">未指定</option>
        <option v-for="u in experimenters" :value="u.id">{{u.name}}（{{roleText(u.role)}}）</option>
      </select></div>
      <div class="form-group"><label>设备</label><select v-model="startForm.equipment_id">
        <option :value="null">选择设备</option>
        <option v-for="e in eq" :value="e.id" :disabled="['停用','报废'].includes(e.status)">{{e.name}}（{{e.exp_type}}）</option>
      </select></div>
      <div class="form-group"><label>预算实验时长(h)</label><input type="number" min="0" step="0.5" v-model.number="startForm.experiment_hours"></div>
      <div class="modal-actions">
        <button class="btn" @click="startTarget=null">取消</button>
        <button class="btn success" @click="confirmStart">确认开始</button>
      </div>
    </div>
  </div>`,
};

/* ---------------- 实验跟踪 ---------------- */
const emptyInsp = () => ({ inspect_at: '', sample_condition: '正常', equipment_condition: '正常', action: '无', schedule_id: null, replacement_sample_id: null, replacement_equipment_id: null, remark: '' });
const ExperimentTrackView = {
  data: () => ({ orders: [], cur: null, detail: null, showModal: false, inspShow: false, insps: [], inspForm: emptyInsp(), poolSamples: [], eq: [] }),
  methods: {
    async load() { this.orders = await api('/api/orders?status='); this.poolSamples = await api('/api/samples?unbound=true'); this.eq = await api('/api/equipment'); },
    async open(o) { this.cur = o; this.detail = await api('/api/orders/' + o.id); this.insps = await api('/api/inspections?order_id=' + o.id); this.showModal = true; },
    openInsp() { this.inspForm = emptyInsp(); this.inspShow = true; },
    runningSchedules() { return (this.detail && this.detail.schedules || []).filter(s => s.status === '实验中'); },
    // 替换样机候选：样品池中可排、且未在本单排期
    replaceSamples() {
      const inOrder = new Set((this.detail && this.detail.schedules || []).map(s => s.sample_id));
      return this.poolSamples.filter(s => ['已接收','已排期','实验中','已完成'].includes(s.status) && !inOrder.has(s.id));
    },
    async saveInsp() {
      try {
        if (this.inspForm.action === '更换样品' || this.inspForm.action === '更换设备') {
          if (!this.inspForm.schedule_id) { toast('请选择要更换的排期（测试位）', 'error'); return; }
        }
        if (this.inspForm.action === '更换样品' && !this.inspForm.replacement_sample_id) { toast('请选择替换样机', 'error'); return; }
        if (this.inspForm.action === '更换设备' && !this.inspForm.replacement_equipment_id) { toast('请选择替换设备', 'error'); return; }
        await api('/api/inspections', 'POST', { ...this.inspForm, order_id: this.cur.id, inspect_at: this.inspForm.inspect_at || null });
        this.inspShow = false; this.open(this.cur); toast('巡检记录已保存', 'success');
      } catch (e) { toast(e.message, 'error'); }
    },
    badge, fmtDT,
  },
  mounted() { this.load(); },
  template: `
  <div class="card">
    <h3>实验跟踪</h3>
    <table class="tbl"><thead><tr><th>实验编号</th><th>委托单位</th><th>检测项目</th><th>状态</th><th>操作</th></tr></thead>
    <tbody>
      <template v-for="o in orders" :key="o.id">
        <tr v-if="o.status==='实验中'">
          <td>{{o.experiment_no||o.order_no}}</td><td>{{o.entrust_org}}</td><td>{{o.test_item}}</td>
          <td v-html="badge(o.status)"></td><td><button class="btn primary sm" @click="open(o)">实验跟踪</button></td>
        </tr>
      </template>
    </tbody></table>
  </div>
  <div class="modal-mask" v-if="showModal" @click.self="showModal=false">
    <div class="modal" style="width:980px">
      <h3>实验跟踪 —— {{cur.experiment_no||cur.order_no}}</h3>
      <h4 style="margin:10px 0 6px">进行中的测试位</h4>
      <table class="tbl"><thead><tr><th>SN</th><th>样品编号</th><th>设备</th><th>实验员</th><th>状态</th><th>实际开始</th></tr></thead>
      <tbody>
        <tr v-for="s in runningSchedules()" :key="s.id">
          <td>{{s.sn||'-'}}</td><td>{{s.sample_no}}</td><td>{{s.equipment_name}}</td><td>{{s.experimenter_name||'-'}}</td>
          <td v-html="badge(s.status)"></td><td>{{fmtDT(s.actual_start)}}</td>
        </tr>
        <tr v-if="!runningSchedules().length"><td colspan="6" class="empty">暂无进行中的实验</td></tr>
      </tbody></table>
      <div style="display:flex;align-items:center;margin:16px 0 6px">
        <h4 style="margin:0;flex:1">巡检记录</h4>
        <button class="btn primary sm" @click="openInsp">+ 新增巡检</button>
      </div>
      <table class="tbl"><thead><tr><th>巡检时间</th><th>巡检人</th><th>样品状况</th><th>设备状况</th><th>处理措施</th><th>处理详情</th><th>备注</th></tr></thead>
      <tbody>
        <tr v-for="x in insps" :key="x.id">
          <td>{{fmtDT(x.inspect_at)}}</td><td>{{x.operator}}</td>
          <td>{{x.sample_condition}}</td><td>{{x.equipment_condition}}</td>
          <td><span v-html="badge(x.action, {'无':'gray','更换样品':'orange','更换设备':'orange','报修':'red'})"></span></td>
          <td>{{x.action_detail||'-'}}</td><td>{{x.remark||'-'}}</td>
        </tr>
        <tr v-if="!insps.length"><td colspan="7" class="empty">暂无巡检记录</td></tr>
      </tbody></table>
      <div class="modal-actions"><button class="btn" @click="showModal=false">关闭</button></div>
    </div>
  </div>
  <div class="modal-mask" v-if="inspShow" @click.self="inspShow=false">
    <div class="modal" style="width:560px">
      <h3>新增巡检记录 —— {{cur.experiment_no||cur.order_no}}</h3>
      <div class="form-row">
        <div class="form-group" style="flex:1"><label>巡检时间</label><input type="datetime-local" v-model="inspForm.inspect_at"></div>
        <div class="form-group" style="flex:1"><label>样品状况</label><select v-model="inspForm.sample_condition"><option>正常</option><option>异常</option></select></div>
        <div class="form-group" style="flex:1"><label>设备状况</label><select v-model="inspForm.equipment_condition"><option>正常</option><option>异常</option></select></div>
      </div>
      <div class="form-group"><label>处理措施</label><select v-model="inspForm.action">
        <option value="无">无</option><option value="更换样品">更换样品</option><option value="更换设备">更换设备</option><option value="报修">报修</option>
      </select></div>
      <div class="form-group" v-if="inspForm.action==='更换样品' || inspForm.action==='更换设备'"><label>目标排期（测试位）</label><select v-model="inspForm.schedule_id">
        <option :value="null">选择测试位</option>
        <option v-for="s in runningSchedules()" :value="s.id">{{s.sample_no}}（SN {{s.sn||'-'}}）→ {{s.equipment_name}}</option>
      </select></div>
      <div class="form-group" v-if="inspForm.action==='更换样品'"><label>替换样机（样品池）</label><select v-model="inspForm.replacement_sample_id">
        <option :value="null">选择替换样机</option>
        <option v-for="s in replaceSamples()" :value="s.id">{{s.sample_no}}（SN {{s.sn||'-'}}，{{s.status}}）</option>
      </select></div>
      <div class="form-group" v-if="inspForm.action==='更换设备'"><label>替换设备</label><select v-model="inspForm.replacement_equipment_id">
        <option :value="null">选择替换设备</option>
        <option v-for="e in eq" :value="e.id" :disabled="['停用','报废'].includes(e.status)">{{e.name}}（{{e.exp_type}}）</option>
      </select></div>
      <div class="form-group"><label>备注</label><textarea v-model="inspForm.remark" rows="3"></textarea></div>
      <div class="modal-actions">
        <button class="btn" @click="inspShow=false">取消</button>
        <button class="btn success" @click="saveInsp">保存巡检记录</button>
      </div>
    </div>
  </div>`,
};

/* ---------------- 实验结束 ---------------- */
const ExperimentEndView = {
  data: () => ({ orders: [], cur: null, detail: null, showModal: false }),
  methods: {
    async load() { this.orders = await api('/api/orders?status='); },
    async open(o) { this.cur = o; this.detail = await api('/api/orders/' + o.id); this.showModal = true; },
    async end(s) { await api('/api/experiment/schedule/' + s.id + '/end', 'POST'); this.open(this.cur); toast('该排期实验已结束', 'success'); },
    async setResult(s, r) { await api('/api/experiment/result', 'PUT', { schedule_id: s.id, result: r }); this.open(this.cur); },
    missingResults() { return (this.detail && this.detail.schedules || []).filter(s => !['OK', 'NG'].includes(s.result)).length; },
    async finish() {
      try { await api('/api/experiment/order/' + this.cur.id + '/finish', 'POST'); toast('实验已完成', 'success'); this.open(this.cur); this.load(); }
      catch (e) { toast(e.message, 'error'); }
    },
    badge, fmtDT,
  },
  mounted() { this.load(); },
  template: `
  <div class="card">
    <h3>实验结束</h3>
    <table class="tbl"><thead><tr><th>实验编号</th><th>委托单位</th><th>检测项目</th><th>状态</th><th>操作</th></tr></thead>
    <tbody>
      <template v-for="o in orders" :key="o.id">
        <tr v-if="['已排期','实验中'].includes(o.status)">
          <td>{{o.experiment_no||o.order_no}}</td><td>{{o.entrust_org}}</td><td>{{o.test_item}}</td>
          <td v-html="badge(o.status)"></td><td><button class="btn primary sm" @click="open(o)">结束实验</button></td>
        </tr>
      </template>
    </tbody></table>
  </div>
  <div class="modal-mask" v-if="showModal" @click.self="showModal=false">
    <div class="modal" style="width:960px">
      <h3>实验结束 —— {{cur.experiment_no||cur.order_no}}</h3>
      <h4 style="margin:10px 0 6px">排期计划</h4>
      <table class="tbl"><thead><tr><th>样品</th><th>设备</th><th>实验员</th><th>状态</th><th>预计开始</th><th>实际开始</th><th>实际结束</th><th>操作</th></tr></thead>
      <tbody>
        <tr v-for="s in detail.schedules" :key="s.id">
          <td>{{s.sample_no}}</td><td>{{s.equipment_name}}</td><td>{{s.experimenter_name||'-'}}</td><td v-html="badge(s.status)"></td>
          <td>{{fmtDT(s.plan_start)}}</td><td>{{fmtDT(s.actual_start)}}</td><td>{{fmtDT(s.actual_end)}}</td>
          <td><button class="btn sm" v-if="s.status==='实验中'" @click="end(s)">结束</button></td>
        </tr>
        <tr v-if="!detail.schedules.length"><td colspan="8" class="empty">暂无排期</td></tr>
      </tbody></table>
      <h4 style="margin:14px 0 6px">测试位实验结果（每行一个测试位，样机可复用）</h4>
      <table class="tbl"><thead><tr><th>SN</th><th>样品编号</th><th>设备</th><th>状态</th><th>实验结果</th></tr></thead>
      <tbody>
        <tr v-for="s in detail.schedules" :key="s.id">
          <td>{{s.sn||'-'}}</td><td>{{s.sample_no}}</td><td>{{s.equipment_name}}</td>
          <td v-html="badge(s.status)"></td>
          <td>
            <div class="result-btns">
              <button class="btn ok" :class="{sel: s.result==='OK'}" @click="setResult(s,'OK')">OK</button>
              <button class="btn ng" :class="{sel: s.result==='NG'}" @click="setResult(s,'NG')">NG</button>
            </div>
          </td>
        </tr>
        <tr v-if="!detail.schedules.length"><td colspan="5" class="empty">暂无排期</td></tr>
      </tbody></table>
      <div class="modal-actions">
        <span v-if="missingResults() > 0" style="color:#b7791f;font-size:12px;margin-right:auto">还有 {{missingResults()}} 条排期未填写实验结果（OK/NG），不能结束</span>
        <button class="btn" @click="showModal=false">关闭</button>
        <button class="btn success" @click="finish" :disabled="detail.status==='已完成' || missingResults() > 0">结束全部实验</button>
      </div>
    </div>
  </div>`,
};

/* ---------------- 实验报告 ---------------- */
const ReportsView = {
  data: () => ({ orders: [], cur: null, detail: null, showModal: false, tab: 'gen', archives: [], archType: '', archKeyword: '', drafts: {}, editChoose: false, editShow: false, editType: '', editVersion: '', editHtml: '', editSaving: false, templates: [], tplPick: false, tplSel: '', tplName: '', tplFile: null, ooEnabled: false, ooUrl: '', ooShow: false, ooEditor: null }),
  methods: {
    async load() { this.orders = await api('/api/orders?status='); this.loadDrafts(); },
    async loadDrafts() {
      const rows = await api('/api/reports/drafts');
      this.drafts = {};
      rows.forEach(d => { const m = this.drafts[d.order_id] || (this.drafts[d.order_id] = {}); m[d.report_type + '|' + d.version] = true; });
    },
    async loadArchive() {
      const q = (this.archType ? 'type=' + encodeURIComponent(this.archType) : '') + (this.archKeyword ? (this.archType ? '&' : '') + 'keyword=' + encodeURIComponent(this.archKeyword) : '');
      this.archives = await api('/api/reports/archive' + (q ? '?' + q : ''));
    },
    switchTab(t) { this.tab = t; if (t === 'arch') this.loadArchive(); if (t === 'tpl') this.loadTemplates(); },
    async open(o) { this.cur = o; this.detail = await api('/api/orders/' + o.id); this.showModal = true; },
    async report(kind, version) {
      // 先同步打开空窗口（避免被浏览器拦截弹窗），再带 token 拉取 HTML 写入
      const w = window.open('', '_blank');
      if (!w) { toast('请允许浏览器弹出新窗口', 'error'); return; }
      try {
        const url = '/api/reports/' + kind + '/' + this.cur.id + (version ? '?version=' + encodeURIComponent(version) : '');
        const html = await api(url);
        w.document.write(html); w.document.close();
      } catch (e) { w.close(); toast(e.message, 'error'); }
    },
    async issue(report_type, version) {
      try { await api('/api/reports/' + this.cur.id + '/issue', 'POST', { report_type, version: version || '' }); toast('已签发并留档', 'success'); }
      catch (e) { toast(e.message, 'error'); }
    },
    async viewArchive(r) {
      const w = window.open('', '_blank');
      if (!w) { toast('请允许浏览器弹出新窗口', 'error'); return; }
      try {
        const html = await api('/api/reports/archive/' + r.id + '/view');
        w.document.write(html); w.document.close();
      } catch (e) { w.close(); toast(e.message, 'error'); }
    },
    async delArchive(r) { if (confirm('确认作废报告 ' + r.report_no + '？')) { await api('/api/reports/archive/' + r.id, 'DELETE'); this.loadArchive(); } },
    async downloadDocx(r) {
      try {
        const headers = {};
        if (state.token) headers['Authorization'] = 'Bearer ' + state.token;
        const res = await fetch('/api/reports/archive/' + r.id + '/docx', { headers });
        if (res.status === 401) { logout(); throw new Error('未登录或登录已过期'); }
        if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error((d && d.detail) || '下载失败'); }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = (r.report_no || 'report') + '_' + r.report_type + '.docx';
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 2000);
      } catch (e) { toast(e.message, 'error'); }
    },
    hasAnyDraft(o) { const m = this.drafts[o.id]; return !!(m && Object.keys(m).length); },
    hasDraftType(o, type, version) { const m = this.drafts[o.id]; return !!(m && m[type + '|' + version]); },
    // —— 报告编辑 ——
    async openEdit(o) { this.cur = o; this.detail = await api('/api/orders/' + o.id); this.editChoose = true; },
    async startEdit(type, version) {
      try {
        const html = await api('/api/reports/edit/' + this.cur.id + '?type=' + encodeURIComponent(type) + '&version=' + encodeURIComponent(version));
        this.editType = type; this.editVersion = version; this.editHtml = html;
        this.editChoose = false; this.editShow = true;
      } catch (e) { toast(e.message, 'error'); }
    },
    _editContent() {
      const doc = this.$refs.editFrame && this.$refs.editFrame.contentDocument;
      if (!doc) return '';
      const el = doc.querySelector('.report');
      if (!el) return doc.body ? doc.body.innerHTML : '';
      const clone = el.cloneNode(true);
      clone.querySelectorAll('[data-edit-only]').forEach(n => n.remove());
      return clone.innerHTML;
    },
    async saveDraft(showMsg = true) {
      const content = this._editContent();
      await api('/api/reports/draft', 'POST', { order_id: this.cur.id, report_type: this.editType, version: this.editVersion, content });
      this.loadDrafts();
      if (showMsg) toast('草稿已保存', 'success');
    },
    previewEdit() {
      const doc = this.$refs.editFrame && this.$refs.editFrame.contentDocument;
      if (!doc) return;
      const w = window.open('', '_blank');
      if (!w) { toast('请允许浏览器弹出新窗口', 'error'); return; }
      let html = '<!DOCTYPE html>' + doc.documentElement.outerHTML;
      html = html.replace('</body>', '<script>window.print()<\/script></body>');
      w.document.write(html); w.document.close();
    },
    async openWord() {
      try {
        await this.saveDraft(false); // 先把当前编辑内容落草稿，Word 打开的是最新内容
        await api('/api/reports/' + this.cur.id + '/word-open?type=' + encodeURIComponent(this.editType) + '&version=' + encodeURIComponent(this.editVersion), 'POST');
        toast('已在 Word 中打开，编辑保存后点「从Word同步」回填', 'success');
      } catch (e) { toast(e.message, 'error'); }
    },
    async syncWord() {
      try {
        await api('/api/reports/' + this.cur.id + '/word-sync?type=' + encodeURIComponent(this.editType) + '&version=' + encodeURIComponent(this.editVersion), 'POST');
        await this.refreshEdit();
        toast('已从 Word 同步到报告', 'success');
      } catch (e) { toast(e.message, 'error'); }
    },
    async refreshEdit() {
      const html = await api('/api/reports/edit/' + this.cur.id + '?type=' + encodeURIComponent(this.editType) + '&version=' + encodeURIComponent(this.editVersion));
      this.editHtml = html;
    },
    // —— OnlyOffice 在线编辑 ——
    async checkOO() {
      try { const r = await api('/api/oo/info'); this.ooEnabled = !!r.enabled; this.ooUrl = r.url || ''; }
      catch (e) { this.ooEnabled = false; }
    },
    async openOnline(type, version) {
      try {
        const config = await api('/api/reports/' + this.cur.id + '/online-open?type=' + encodeURIComponent(type) + '&version=' + encodeURIComponent(version), 'POST');
        this.editType = type; this.editVersion = version;
        this.ooShow = true;
        this.$nextTick(() => this.mountOO(config));
      } catch (e) { toast(e.message, 'error'); }
    },
    mountOO(config) {
      loadOO(this.ooUrl).then(D => {
        if (!D) { toast('加载 OnlyOffice 编辑器脚本失败', 'error'); return; }
        if (this.ooEditor) { try { this.ooEditor.destroyEditor(); } catch (e) {} this.ooEditor = null; }
        this.ooEditor = new D.DocEditor('onlyoffice-editor', config);
      });
    },
    closeOO() {
      if (this.ooEditor) { try { this.ooEditor.destroyEditor(); } catch (e) {} this.ooEditor = null; }
      this.ooShow = false;
      this.loadDrafts();
    },
    // —— 自定义报告模板库 ——
    async loadTemplates() { this.templates = await api('/api/report-templates'); },
    onTplFile(e) { this.tplFile = e.target.files && e.target.files[0] || null; },
    async uploadTpl() {
      if (!this.tplName.trim()) { toast('请填写模板名称', 'error'); return; }
      if (!this.tplFile) { toast('请选择 .docx 模板文件', 'error'); return; }
      const fd = new FormData();
      fd.append('name', this.tplName.trim());
      fd.append('file', this.tplFile);
      const headers = {};
      if (state.token) headers['Authorization'] = 'Bearer ' + state.token;
      try {
        const res = await fetch('/api/report-templates', { method: 'POST', headers, body: fd });
        const data = await res.json().catch(() => ({}));
        if (res.status === 401) { logout(); throw new Error('未登录或登录已过期'); }
        if (!res.ok) throw new Error((data && data.detail) || '上传失败');
        this.tplName = ''; this.tplFile = null;
        await this.loadTemplates();
        toast('模板已上传', 'success');
      } catch (e) { toast(e.message, 'error'); }
    },
    async setDefaultTpl(t) { await api('/api/report-templates/' + t.id + '/default', 'POST'); await this.loadTemplates(); toast('已设为默认', 'success'); },
    async delTpl(t) { if (confirm('确认删除模板「' + t.name + '」？')) { await api('/api/report-templates/' + t.id, 'DELETE'); await this.loadTemplates(); } },
    openTplPick() {
      if (!this.templates.length) { toast('还没有报告模板，请先切到「模板库」Tab 上传 .docx 模板', 'error'); return; }
      const d = this.templates.find(t => t.is_default);
      this.tplSel = d ? d.name : this.templates[0].name;
      this.tplPick = true;
    },
    async startCustomEdit() {
      if (!this.tplSel) { toast('请选择模板', 'error'); return; }
      this.tplPick = false;
      await this.startEdit('自定义报告', this.tplSel);
    },
    customDrafts(o) {
      const m = this.drafts[o.id]; if (!m) return [];
      return Object.keys(m).filter(k => k.indexOf('自定义报告|') === 0).map(k => k.slice('自定义报告|'.length));
    },
    badge,
  },
  mounted() { this.load(); this.loadTemplates(); this.checkOO(); },
  template: `
  <div>
    <div class="tabs">
      <button class="tab" :class="{active:tab==='gen'}" @click="switchTab('gen')">生成报告</button>
      <button class="tab" :class="{active:tab==='arch'}" @click="switchTab('arch')">归档列表</button>
      <button class="tab" :class="{active:tab==='tpl'}" @click="switchTab('tpl')">模板库</button>
    </div>
    <div class="card" v-if="tab==='gen'">
      <h3>实验报告</h3>
      <table class="tbl"><thead><tr><th>实验编号</th><th>委托单位</th><th>检测项目</th><th>状态</th><th>操作</th></tr></thead>
      <tbody>
        <template v-for="o in orders" :key="o.id">
          <tr v-if="o.status!=='待审核' && o.status!=='已否决'">
            <td><a class="link" @click="openEdit(o)">{{o.experiment_no||o.order_no}}</a></td><td>{{o.entrust_org}}</td><td>{{o.test_item}}</td>
            <td v-html="badge(o.status)"></td><td><button class="btn primary sm" :disabled="!hasAnyDraft(o)" @click="open(o)">生成报告</button></td>
          </tr>
        </template>
      </tbody></table>
    </div>
    <div class="card" v-if="tab==='arch'">
      <div class="toolbar"><h3 style="flex:1">归档报告</h3>
        <select v-model="archType" @change="loadArchive"><option value="">全部类型</option><option>委托记录单</option><option>检测报告</option></select>
        <input v-model="archKeyword" placeholder="编号/样品/单位关键字" @keyup.enter="loadArchive"><button class="btn primary" @click="loadArchive">查询</button></div>
      <table class="tbl"><thead><tr><th>报告编号</th><th>委托/实验编号</th><th>委托单位</th><th>类型</th><th>版本</th><th>状态</th><th>签发时间</th><th>操作</th></tr></thead>
      <tbody>
        <tr v-for="r in archives" :key="r.id">
          <td>{{r.report_no}}</td><td>{{r.order_no}} / {{r.experiment_no||'-'}}</td><td>{{r.entrust_org}}</td><td>{{r.report_type}}</td><td>{{r.version||'-'}}</td>
          <td v-html="badge(r.status)"></td><td>{{fmtDT(r.issued_at)}}</td>
          <td><button class="btn link" @click="viewArchive(r)">查看</button><button class="btn link" v-if="r.has_docx" @click="downloadDocx(r)">下载Word</button><button class="btn link" v-if="state.role==='admin'" @click="delArchive(r)">作废</button></td>
        </tr>
        <tr v-if="!archives.length"><td colspan="8" class="empty">暂无归档报告</td></tr>
      </tbody></table>
    </div>
    <div class="card" v-if="tab==='tpl'">
      <h3>报告模板库</h3>
      <div class="toolbar" style="margin-bottom:10px">
        <input v-model="tplName" placeholder="模板名称（如：可靠性报告）" style="flex:1">
        <input type="file" accept=".docx" @change="onTplFile">
        <button class="btn primary" @click="uploadTpl">上传模板</button>
      </div>
      <p style="color:#6b7a90;font-size:12px;margin-bottom:10px">模板中可预埋占位符（如 {{委托单位}}、{{实验编号}}），生成自定义报告时系统会自动替换为委托单里的实际信息，其余内容在线手动编辑。</p>
      <table class="tbl"><thead><tr><th>模板名称</th><th>文件</th><th>默认</th><th>上传时间</th><th>操作</th></tr></thead>
      <tbody>
        <tr v-for="t in templates" :key="t.id">
          <td>{{t.name}}</td><td>{{t.filename}}</td>
          <td><span v-if="t.is_default" class="badge green">默认</span></td>
          <td>{{fmtDT(t.created_at)}}</td>
          <td>
            <button class="btn link" v-if="!t.is_default" @click="setDefaultTpl(t)">设为默认</button>
            <button class="btn link" @click="delTpl(t)">删除</button>
          </td>
        </tr>
        <tr v-if="!templates.length"><td colspan="5" class="empty">暂无模板，请上传 .docx 模板</td></tr>
      </tbody></table>
    </div>
    <div class="modal-mask" v-if="showModal" @click.self="showModal=false">
      <div class="modal" style="width:520px">
        <h3>生成报告</h3>
        <p style="margin-bottom:16px;color:#6b7a90">实验编号：{{cur.experiment_no||cur.order_no}}　|　{{cur.test_item}}</p>
        <p style="margin-bottom:10px;color:#b7791f;font-size:12px">报告内容以「实验编号 → 编辑」保存的为准，未编辑的类型不可生成。</p>
        <button class="btn primary" style="width:100%;margin-bottom:10px" :disabled="!hasDraftType(cur,'委托记录单','')" @click="report('entrust')">实验委托记录单（表-TC05-01A）</button>
        <p v-if="detail.status!=='已完成'" style="color:#b7791f;font-size:12px;margin:0 0 10px">实验未完成（当前 {{detail.status}}），检测报告需在「实验结束」中结束全部实验并填写结果后生成</p>
        <button class="btn" style="width:100%;margin-bottom:10px" :disabled="detail.status!=='已完成' || !hasDraftType(cur,'检测报告','常规')" @click="report('test','常规')">检测报告（常规版）</button>
        <button class="btn" style="width:100%" :disabled="detail.status!=='已完成' || !hasDraftType(cur,'检测报告','检测')" @click="report('test','检测')">检测报告（检测版）</button>
        <template v-if="customDrafts(cur).length">
          <div style="border-top:1px dashed #e2e8f0;margin:14px 0;padding-top:12px">
            <h4 style="margin-bottom:10px">自定义报告</h4>
            <div v-for="tn in customDrafts(cur)" :key="tn" class="form-row" style="margin-bottom:8px">
              <span style="flex:1;line-height:32px">{{tn}}</span>
              <button class="btn" style="flex:1" @click="report('custom', tn)">生成(打印)</button>
              <button class="btn" style="flex:1" @click="issue('自定义报告', tn)">签发</button>
            </div>
          </div>
        </template>
        <div style="border-top:1px dashed #e2e8f0;margin:16px 0;padding-top:14px">
          <h4 style="margin-bottom:10px">签发并留档</h4>
          <div class="form-row">
            <button class="btn" style="flex:1" @click="issue('委托记录单','')">签发委托记录单</button>
            <button class="btn" style="flex:1" :disabled="detail.status!=='已完成'" @click="issue('检测报告','常规')">签发检测报告(常规)</button>
            <button class="btn" style="flex:1" :disabled="detail.status!=='已完成'" @click="issue('检测报告','检测')">签发检测报告(检测)</button>
          </div>
        </div>
        <div class="modal-actions"><button class="btn" @click="showModal=false">关闭</button></div>
      </div>
    </div>
    <div class="modal-mask" v-if="editChoose" @click.self="editChoose=false">
      <div class="modal" style="width:520px">
        <h3>编辑报告 —— 选择类型</h3>
        <p style="margin-bottom:16px;color:#6b7a90">实验编号：{{cur.experiment_no||cur.order_no}}　|　{{cur.test_item}}</p>
        <button class="btn primary" style="width:100%;margin-bottom:10px" @click="startEdit('委托记录单','')">编辑委托记录单（表-TC05-01A）</button>
        <p v-if="detail.status!=='已完成'" style="color:#b7791f;font-size:12px;margin:0 0 10px">实验未完成（当前 {{detail.status}}），检测报告需在「实验结束」中结束全部实验并填写结果后编辑</p>
        <button class="btn" style="width:100%;margin-bottom:10px" :disabled="detail.status!=='已完成'" @click="startEdit('检测报告','常规')">编辑检测报告（常规版）</button>
        <button class="btn" style="width:100%" :disabled="detail.status!=='已完成'" @click="startEdit('检测报告','检测')">编辑检测报告（检测版）</button>
        <button class="btn" style="width:100%" :disabled="detail.status!=='已完成'" @click="openTplPick()">编辑自定义报告</button>
        <div class="modal-actions"><button class="btn" @click="editChoose=false">关闭</button></div>
      </div>
    </div>
    <div class="modal-mask" v-if="tplPick" @click.self="tplPick=false">
      <div class="modal" style="width:520px">
        <h3>选择报告模板</h3>
        <p style="margin-bottom:12px;color:#6b7a90">实验编号：{{cur.experiment_no||cur.order_no}}　|　{{cur.test_item}}</p>
        <div v-for="t in templates" :key="t.id" style="margin-bottom:8px;display:flex;align-items:center;gap:8px">
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
            <input type="radio" :value="t.name" v-model="tplSel">{{t.name}}<span v-if="t.is_default" class="badge green">默认</span>
          </label>
        </div>
        <div class="modal-actions">
          <button class="btn" @click="tplPick=false">取消</button>
          <button class="btn primary" @click="startCustomEdit">使用此模板编辑</button>
        </div>
      </div>
    </div>
    <div class="modal-mask" v-if="editShow" @click.self="editShow=false">
      <div class="modal report-edit-modal">
        <div class="toolbar" style="margin-bottom:10px">
          <h3 style="flex:1;margin:0">报告编辑 —— {{editType}}{{editVersion ? '（' + editVersion + '版）' : ''}}</h3>
          <button class="btn sm" @click="saveDraft()">保存草稿</button>
          <button class="btn sm" @click="previewEdit()">预览打印</button>
          <button class="btn sm" @click="openWord()">启动Word编辑</button>
          <button class="btn sm primary" v-if="ooEnabled" @click="openOnline(editType, editVersion)">在线编辑</button>
          <button class="btn sm" @click="syncWord()">从Word同步</button>
          <button class="btn sm" @click="editShow=false">关闭</button>
        </div>
        <iframe ref="editFrame" class="report-edit-frame" :srcdoc="editHtml"></iframe>
      </div>
    </div>
    <div class="modal-mask" v-if="ooShow" @click.self="closeOO()">
      <div class="modal oo-modal">
        <div class="toolbar" style="margin-bottom:10px">
          <h3 style="flex:1;margin:0">在线编辑 —— {{editType}}{{editVersion ? '（' + editVersion + '版）' : ''}}</h3>
          <span style="font-size:12px;color:var(--muted)">编辑后自动保存回报告存档，关闭即生效</span>
          <button class="btn sm" @click="closeOO()">关闭</button>
        </div>
        <div id="onlyoffice-editor" class="oo-editor-host"></div>
      </div>
    </div>
  </div>`,
};

/* ---------------- 设备管理 ---------------- */
const EquipmentView = {
  data: () => ({ list: [], showModal: false, editing: null, form: emptyEq(), types: ['环境类测试', '运输类测试', '机械类测试', '表面类测试', '防水测试', '电性能类', '其它试验'], maintEq: null, maintList: [], maintShow: false, maintForm: emptyMaint(), maintEditing: null, maintFormShow: false, maintTypes: ['校准', '维修', '保养'] }),
  methods: {
    async load() { this.list = await api('/api/equipment'); },
    add() { this.editing = null; this.form = emptyEq(); this.showModal = true; },
    edit(e) { this.editing = e; this.form = { ...e, valid_from: fmtLocal(e.valid_from), valid_to: fmtLocal(e.valid_to) }; this.showModal = true; },
    async save() {
      try {
        const payload = { ...this.form };
        if (!payload.valid_from) payload.valid_from = null;
        if (!payload.valid_to) payload.valid_to = null;
        if (this.editing) await api('/api/equipment/' + this.editing.id, 'PUT', payload);
        else await api('/api/equipment', 'POST', payload);
        this.showModal = false; this.load(); toast('保存成功', 'success');
      } catch (e) { toast(e.message, 'error'); }
    },
    async stop(e) { await api('/api/equipment/' + e.id + '/stop', 'POST'); this.load(); },
    async del(e) { if (confirm('确认删除设备 ' + e.name + '？')) { await api('/api/equipment/' + e.id, 'DELETE'); this.load(); } },
    async openMaint(e) { this.maintEq = e; this.maintList = await api('/api/equipment/' + e.id + '/maintenance'); this.maintShow = true; },
    addMaint() { this.maintEditing = null; this.maintForm = emptyMaint(); this.maintFormShow = true; },
    editMaint(m) { this.maintEditing = m; this.maintForm = { ...m, date: fmtD(m.date), next_date: fmtD(m.next_date) }; this.maintFormShow = true; },
    async saveMaint() {
      try {
        const payload = { ...this.maintForm };
        if (!payload.date) payload.date = null;
        if (!payload.next_date) payload.next_date = null;
        if (this.maintEditing) await api('/api/equipment/maintenance/' + this.maintEditing.id, 'PUT', payload);
        else await api('/api/equipment/' + this.maintEq.id + '/maintenance', 'POST', payload);
        this.maintList = await api('/api/equipment/' + this.maintEq.id + '/maintenance');
        this.maintEditing = null; this.maintForm = emptyMaint(); this.maintFormShow = false; toast('保存成功', 'success');
      } catch (e) { toast(e.message, 'error'); }
    },
    async delMaint(m) { if (confirm('确认删除该记录？')) { await api('/api/equipment/maintenance/' + m.id, 'DELETE'); this.maintList = await api('/api/equipment/' + this.maintEq.id + '/maintenance'); } },
    badge: (s) => `<span class="badge ${s==='可用'?'green':s==='使用中'?'orange':s==='停用'?'gray':'red'}">${s}</span>`,
    fmtD,
  },
  mounted() { this.load(); },
  template: `
  <div class="card">
    <div class="toolbar"><h3 style="flex:1">实验设备列表</h3>
      <button class="btn primary" @click="add" v-if="state.role==='admin'">添加设备</button></div>
    <table class="tbl"><thead><tr><th>排序</th><th>名称</th><th>型号</th><th>编号</th><th>实验类型</th><th>开机费</th><th>电费/小时</th><th>设备折旧/小时</th><th>耗材费用/小时</th><th>设备单价</th><th>设备功率(kW)</th><th>状态</th><th>管理</th></tr></thead>
    <tbody>
      <tr v-for="e in list" :key="e.id">
        <td>{{e.sort_order}}</td><td>{{e.name}}</td><td>{{e.model}}</td><td>{{e.code}}</td><td>{{e.exp_type}}</td>
        <td>{{e.open_fee}}</td><td>{{e.power_fee}}</td><td>{{e.depreciation_fee}}</td><td>{{e.consumable_fee}}</td><td>{{e.unit_price}}</td><td>{{e.power_kw}}</td><td v-html="badge(e.status)"></td>
        <td>
          <button class="btn link" @click="openMaint(e)">校准/维保</button>
          <button class="btn link" @click="edit(e)">修改</button>
          <button class="btn link" @click="stop(e)">{{ e.status==='停用'||e.status==='报废' ? '启用' : '停用' }}</button>
          <button class="btn link" @click="del(e)">删除</button>
        </td>
      </tr>
    </tbody></table>
  </div>
  <div class="modal-mask" v-if="showModal" @click.self="showModal=false">
    <div class="modal" style="width:640px">
      <h3>{{editing?'修改设备':'添加设备'}}</h3>
      <div class="form-row">
        <div class="form-group"><label>排序</label><input type="number" v-model.number="form.sort_order"></div>
        <div class="form-group"><label>名称</label><input v-model="form.name"></div>
        <div class="form-group"><label>型号</label><input v-model="form.model"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>编号</label><input v-model="form.code"></div>
        <div class="form-group"><label>实验类型</label><select v-model="form.exp_type"><option v-for="t in types" :value="t">{{t}}</option></select></div>
        <div class="form-group"><label>状态</label><select v-model="form.status"><option>可用</option><option>使用中</option><option>停用</option><option>报废</option></select></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>开机费(元)</label><input type="number" v-model.number="form.open_fee"></div>
        <div class="form-group"><label>电费/小时</label><input type="number" v-model.number="form.power_fee"></div>
        <div class="form-group"><label>设备折旧/小时</label><input type="number" v-model.number="form.depreciation_fee"></div>
        <div class="form-group"><label>耗材费用/小时</label><input type="number" v-model.number="form.consumable_fee"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>设备单价(元)</label><input type="number" v-model.number="form.unit_price"></div>
        <div class="form-group"><label>设备功率(kW)</label><input type="number" v-model.number="form.power_kw"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>有效期开始</label><input type="datetime-local" v-model="form.valid_from"></div>
        <div class="form-group"><label>有效期结束</label><input type="datetime-local" v-model="form.valid_to"></div>
      </div>
      <div class="form-group"><label>备注</label><textarea v-model="form.remark"></textarea></div>
      <div class="modal-actions"><button class="btn" @click="showModal=false">取消</button><button class="btn primary" @click="save">保存</button></div>
    </div>
  </div>
  <div class="modal-mask" v-if="maintShow" @click.self="maintShow=false">
    <div class="modal" style="width:720px">
      <div class="toolbar"><h3 style="flex:1">{{maintEq.name}} —— 校准/维保记录</h3><button class="btn primary sm" @click="addMaint">新增记录</button></div>
      <table class="tbl"><thead><tr><th>类型</th><th>日期</th><th>下次到期</th><th>费用</th><th>操作人</th><th>备注</th><th>操作</th></tr></thead>
      <tbody>
        <tr v-for="m in maintList" :key="m.id">
          <td>{{m.type}}</td><td>{{fmtD(m.date)}}</td><td>{{fmtD(m.next_date)}}</td><td>{{m.cost}}</td><td>{{m.operator||'-'}}</td><td>{{m.note||'-'}}</td>
          <td><button class="btn link" @click="editMaint(m)">修改</button><button class="btn link" @click="delMaint(m)">删除</button></td>
        </tr>
        <tr v-if="!maintList.length"><td colspan="7" class="empty">暂无记录</td></tr>
      </tbody></table>
      <div v-if="maintFormShow" style="border-top:1px dashed #e2e8f0;margin-top:14px;padding-top:12px">
        <h4 style="margin-bottom:10px">{{maintEditing?'修改记录':'新增记录'}}</h4>
        <div class="form-row">
          <div class="form-group"><label>类型</label><select v-model="maintForm.type"><option v-for="t in maintTypes" :value="t">{{t}}</option></select></div>
          <div class="form-group"><label>日期</label><input type="date" v-model="maintForm.date"></div>
          <div class="form-group"><label>下次到期</label><input type="date" v-model="maintForm.next_date"></div>
        </div>
        <div class="form-row">
          <div class="form-group"><label>费用</label><input type="number" v-model.number="maintForm.cost"></div>
          <div class="form-group"><label>操作人</label><input v-model="maintForm.operator"></div>
        </div>
        <div class="form-group"><label>备注</label><input v-model="maintForm.note"></div>
        <button class="btn primary" @click="saveMaint">保存记录</button>
      </div>
      <div class="modal-actions"><button class="btn" @click="maintShow=false">关闭</button></div>
    </div>
  </div>`,
};
function emptyEq() {
  return { name: '', model: '', code: '', exp_type: '其它试验', sort_order: 0, status: '可用', open_fee: 0, power_fee: 0, depreciation_fee: 0, consumable_fee: 0, unit_price: 0, power_kw: 0, valid_from: '', valid_to: '', remark: '' };
}
function emptyMaint() {
  return { type: '校准', date: '', next_date: '', cost: 0, operator: '', note: '' };
}

/* ---------------- 展板 ---------------- */
const BoardsView = {
  data: () => ({ boards: {} }),
  methods: {
    async load() { this.boards = await api('/api/dashboard/boards'); },
    badge, fmtDT,
  },
  mounted() { this.load(); },
  template: `
  <div>
    <div class="card"><h3>待试验展板</h3>
      <table class="tbl"><thead><tr><th>编号</th><th>检测项目</th><th>产品型号</th><th>委托单位</th><th>委托人</th><th>计划开始</th><th>总用时</th><th>设备清单</th></tr></thead>
      <tbody><tr v-for="o in boards.waiting" :key="o.id">
        <td>{{o.experiment_no||o.order_no}}</td><td>{{o.test_item}}</td><td>{{o.sample_model}}</td><td>{{o.entrust_org}}</td><td>{{o.entruster}}</td>
        <td>{{fmtDT(o.plan_start_min)}}</td><td>{{o.total_hours_sum||0}} h</td><td>{{o.equipment_list}}</td>
      </tr><tr v-if="!boards.waiting||!boards.waiting.length"><td colspan="8" class="empty">暂无待试验</td></tr></tbody></table>
    </div>
    <div class="two-col">
      <div class="card"><h3>设备使用明细</h3>
        <table class="tbl"><thead><tr><th>设备</th><th>实验编号</th><th>样品</th><th>开始时间</th><th>预计结束</th></tr></thead>
        <tbody><tr v-for="(u,i) in boards.usage" :key="i"><td>{{u.equipment_name}}</td><td>{{u.order_no}}</td><td>{{u.sample_no}}</td><td>{{fmtDT(u.actual_start)}}</td><td>{{fmtDT(u.plan_end)}}</td></tr>
        <tr v-if="!boards.usage||!boards.usage.length"><td colspan="5" class="empty">暂无使用中设备</td></tr></tbody></table>
      </div>
      <div class="card"><h3>设备排期展板</h3>
        <table class="tbl"><thead><tr><th>设备</th><th>实验编号</th><th>样品</th><th>计划开始</th><th>计划结束</th></tr></thead>
        <tbody><tr v-for="(s,i) in boards.schedule_board" :key="i"><td>{{s.equipment_name}}</td><td>{{s.order_no}}</td><td>{{s.sample_no}}</td><td>{{fmtDT(s.plan_start)}}</td><td>{{fmtDT(s.plan_end)}}</td></tr>
        <tr v-if="!boards.schedule_board||!boards.schedule_board.length"><td colspan="5" class="empty">暂无排期</td></tr></tbody></table>
      </div>
    </div>
  </div>`,
};

/* ---------------- 交接班 ---------------- */
const HandoverView = {
  data: () => ({ list: [], orders: [], form: { order_id: null, note: '' } }),
  methods: {
    async load() { const [l, o] = await Promise.all([api('/api/dashboard/handover'), api('/api/orders?status=')]); this.list = l; this.orders = o; },
    async submit() {
      if (!this.form.note) { toast('请填写注意事项', 'error'); return; }
      await api('/api/dashboard/handover', 'POST', this.form); this.form.note = ''; this.form.order_id = null; this.load(); toast('已记录', 'success');
    },
    fmtDT,
  },
  mounted() { this.load(); },
  template: `
  <div class="two-col">
    <div class="card"><h3>新增交接记录</h3>
      <div class="form-group"><label>关联委托单</label><select v-model="form.order_id"><option :value="null">不关联</option><option v-for="o in orders" :value="o.id">{{o.experiment_no||o.order_no}} {{o.test_item}}</option></select></div>
      <div class="form-group"><label>注意事项</label><textarea v-model="form.note" rows="4"></textarea></div>
      <button class="btn primary" @click="submit">保存</button>
    </div>
    <div class="card"><h3>日夜班交接记录</h3>
      <table class="tbl"><thead><tr><th>时间</th><th>关联委托</th><th>记录人</th><th>注意事项</th></tr></thead>
      <tbody><tr v-for="h in list" :key="h.id"><td>{{fmtDT(h.created_at)}}</td><td>{{h.order_no||'-'}}</td><td>{{h.operator}}</td><td>{{h.note}}</td></tr>
      <tr v-if="!list.length"><td colspan="4" class="empty">暂无交接记录</td></tr></tbody></table>
    </div>
  </div>`,
};

/* ---------------- 用户管理 ---------------- */
const UsersView = {
  data: () => ({ list: [], showModal: false, editing: null, form: emptyUser() }),
  methods: {
    async load() { this.list = await api('/api/auth/users'); },
    add() { this.editing = null; this.form = emptyUser(); this.showModal = true; },
    edit(u) { this.editing = u; this.form = { username: u.username, name: u.name, role: u.role, department: u.department, email: u.email, phone: u.phone, password: '' }; this.showModal = true; },
    async save() {
      try {
        if (this.editing) await api('/api/auth/users/' + this.editing.id, 'PUT', this.form);
        else await api('/api/auth/users', 'POST', this.form);
        this.showModal = false; this.load(); toast('保存成功', 'success');
      } catch (e) { toast(e.message, 'error'); }
    },
    roleText,
  },
  mounted() { this.load(); },
  template: `
  <div class="card">
    <div class="toolbar"><h3 style="flex:1">用户管理</h3><button class="btn primary" @click="add">添加用户</button></div>
    <table class="tbl"><thead><tr><th>用户名</th><th>姓名</th><th>角色</th><th>部门</th><th>邮箱</th><th>电话</th><th>状态</th><th>操作</th></tr></thead>
    <tbody><tr v-for="u in list" :key="u.id">
      <td>{{u.username}}</td><td>{{u.name}}</td><td>{{roleText(u.role)}}</td><td>{{u.department}}</td><td>{{u.email}}</td><td>{{u.phone}}</td>
      <td>{{u.is_active?'启用':'停用'}}</td><td><button class="btn link" @click="edit(u)">修改</button></td>
    </tr></tbody></table>
  </div>
  <div class="modal-mask" v-if="showModal" @click.self="showModal=false">
    <div class="modal" style="width:560px"><h3>{{editing?'修改用户':'添加用户'}}</h3>
      <div class="form-row">
        <div class="form-group"><label>用户名</label><input v-model="form.username" :disabled="!!editing"></div>
        <div class="form-group"><label>姓名</label><input v-model="form.name"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>角色</label><select v-model="form.role"><option value="admin">管理员</option><option value="experimenter">实验员</option><option value="entruster">委托人</option></select></div>
        <div class="form-group"><label>密码</label><input type="password" v-model="form.password" :placeholder="editing?'留空则不修改':'默认 123456'"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>部门</label><input v-model="form.department"></div>
        <div class="form-group"><label>电话</label><input v-model="form.phone"></div>
      </div>
      <div class="form-group"><label>邮箱</label><input v-model="form.email"></div>
      <div class="modal-actions"><button class="btn" @click="showModal=false">取消</button><button class="btn primary" @click="save">保存</button></div>
    </div>
  </div>`,
};
function emptyUser() { return { username: '', name: '', role: 'experimenter', department: '', email: '', phone: '', password: '' }; }

/* ---------------- 统计图表 ---------------- */
const StatisticsView = {
  data: () => ({
    overview: {}, trendLabels: [], trendLines: [], costByItem: [], costByMonth: [],
    usage: [], workload: [], resultDist: [],
    detail: { open: false, type: '', key: '', title: '', cols: [], rows: [] },
  }),
  methods: {
    async load() {
      try {
        this.overview = await api('/api/statistics/overview');
        const trend = await api('/api/statistics/trend?days=30');
        this.trendLabels = trend.map(t => t.date); // 完整日期，供下钻查询
        this.trendLines = [
          { name: '委托', data: trend.map(t => t.created) },
          { name: '完成', data: trend.map(t => t.finished) },
        ];
        const cost = await api('/api/statistics/cost');
        this.costByItem = cost.by_item.map(c => ({ label: c.name, value: c.value }));
        this.costByMonth = cost.by_month.map(c => ({ label: c.name, value: c.value }));
        this.usage = (await api('/api/statistics/equipment-usage')).map(u => ({ label: u.name, value: u.hours }));
        this.workload = (await api('/api/statistics/workload')).map(w => ({ label: w.name, value: w.orders }));
        this.resultDist = (await api('/api/statistics/result-distribution')).map(d => ({ label: d.name, value: d.value }));
      } catch (e) { toast(e.message, 'error'); }
    },
    async onChartClick(type, key) {
      const meta = this.detailMeta(type, key);
      if (!meta) return;
      this.detail = { open: true, type, key, title: meta.title, cols: meta.cols, rows: [] };
      try {
        this.detail.rows = await api('/api/statistics/detail?type=' + encodeURIComponent(type) + '&key=' + encodeURIComponent(key));
      } catch (e) { toast(e.message, 'error'); }
    },
    detailMeta(type, key) {
      const ORD = [
        { k: 'order_no', t: '委托编号' }, { k: 'experiment_no', t: '实验编号' },
        { k: 'entrust_org', t: '委托单位' },
        { k: 'test_item', t: '检测项目' }, { k: 'status', t: '状态' },
        { k: 'total_cost', t: '费用' }, { k: 'created_at', t: '委托时间' }, { k: 'finish_at', t: '完成时间' },
      ];
      const map = {
        trend: { title: key + ' 委托/完成明细', cols: ORD },
        cost_item: { title: '检测项目「' + key + '」费用明细', cols: ORD },
        cost_month: { title: key + ' 月度费用明细', cols: ORD },
        workload: { title: '实验员「' + key + '」委托明细', cols: ORD },
        equipment: { title: '设备「' + key + '」使用明细', cols: [
          { k: 'sample_no', t: '样品编号' }, { k: 'equipment_name', t: '设备' },
          { k: 'experiment_hours', t: '实验用时' }, { k: 'transition_hours', t: '过渡用时' },
          { k: 'total_hours', t: '总用时' }, { k: 'status', t: '状态' },
          { k: 'actual_start', t: '实际开始' }, { k: 'actual_end', t: '实际结束' },
        ] },
        result: { title: '实验结果「' + key + '」样品明细', cols: [
          { k: 'sample_no', t: '样品编号' }, { k: 'status', t: '状态' },
          { k: 'condition', t: '状况' }, { k: 'result', t: '结果' },
          { k: 'remark', t: '备注' }, { k: 'created_at', t: '生成时间' },
        ] },
      };
      return map[type] || null;
    },
    cellVal(row, k) {
      const v = row[k];
      if (v == null || v === '') return '-';
      if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(v)) return fmtDT(v);
      return v;
    },
    statusBadge(r) { return badge(r.status, this.detail.type === 'result' ? SAMPLE_STATUS : ORDER_STATUS); },
    lineChart, barChart, donutChart,
  },
  mounted() {
    window.__chartClick = (type, key) => this.onChartClick(type, key);
    this.load();
  },
  beforeUnmount() { if (window.__chartClick) window.__chartClick = null; },
  template: `
  <div>
    <p class="chart-hint">提示：点击图表中的柱子、数据点或扇区，可查看对应明细。</p>
    <div class="grid-stats">
      <div class="stat b"><div class="num">{{overview.total_orders||0}}</div><div class="label">委托单总数</div></div>
      <div class="stat"><div class="num">{{overview.in_progress||0}}</div><div class="label">在途</div></div>
      <div class="stat g"><div class="num">{{overview.finished||0}}</div><div class="label">已完成</div></div>
      <div class="stat o"><div class="num">{{overview.total_cost||0}}</div><div class="label">费用总额(元)</div></div>
      <div class="stat"><div class="num">{{overview.avg_cycle||0}}</div><div class="label">平均周期(天)</div></div>
      <div class="stat"><div class="num">{{overview.total_equipment||0}}</div><div class="label">设备</div></div>
    </div>
    <div class="card"><h3>委托 / 完成趋势（近30天）</h3><div v-html="lineChart(trendLabels, trendLines, {ctype:'trend'})"></div></div>
    <div class="two-col">
      <div class="card"><h3>各检测项目费用</h3><div v-html="barChart(costByItem, {ctype:'cost_item'})"></div></div>
      <div class="card"><h3>实验结果分布</h3><div v-html="donutChart(resultDist, {ctype:'result'})"></div></div>
    </div>
    <div class="two-col">
      <div class="card"><h3>设备使用时长（小时）</h3><div v-html="barChart(usage, {ctype:'equipment'})"></div></div>
      <div class="card"><h3>实验员委托量</h3><div v-html="barChart(workload, {ctype:'workload'})"></div></div>
    </div>
    <div class="card"><h3>月度费用</h3><div v-html="barChart(costByMonth, {ctype:'cost_month'})"></div></div>

    <div class="modal-mask" v-if="detail.open" @click.self="detail.open=false">
      <div class="modal" style="width:900px">
        <h3>{{detail.title}}</h3>
        <p class="chart-hint" v-if="detail.rows.length">共 {{detail.rows.length}} 条记录</p>
        <table class="tbl"><thead><tr><th v-for="c in detail.cols" :key="c.k">{{c.t}}</th></tr></thead>
        <tbody>
          <tr v-for="(r,i) in detail.rows" :key="i">
            <td v-for="c in detail.cols" :key="c.k">
              <span v-if="c.k==='status'" v-html="statusBadge(r)"></span>
              <span v-else-if="c.k==='result'" :class="{'c-ok': r.result==='OK', 'c-ng': r.result==='NG'}">{{r.result||'-'}}</span>
              <span v-else>{{cellVal(r, c.k)}}</span>
            </td>
          </tr>
          <tr v-if="!detail.rows.length"><td :colspan="detail.cols.length" class="empty">该维度暂无明细记录</td></tr>
        </tbody></table>
        <div class="modal-actions"><button class="btn" @click="detail.open=false">关闭</button></div>
      </div>
    </div>
  </div>`,
};

/* ---------------- 审计日志 ---------------- */
const AuditLogView = {
  data: () => ({ list: [], total: 0, page: 1, size: 50, action: '', username: '', keyword: '' }),
  methods: {
    async load() {
      const q = new URLSearchParams();
      q.set('page', this.page); q.set('size', this.size);
      if (this.action) q.set('action', this.action);
      if (this.username) q.set('username', this.username);
      if (this.keyword) q.set('keyword', this.keyword);
      const r = await api('/api/audit?' + q.toString());
      this.list = r.items; this.total = r.total;
    },
    async search() { this.page = 1; this.load(); },
    async prev() { if (this.page > 1) { this.page--; this.load(); } },
    async next() { if (this.page * this.size < this.total) { this.page++; this.load(); } },
    fmtDT,
  },
  mounted() { this.load(); },
  template: `
  <div class="card">
    <h3>审计日志</h3>
    <div class="toolbar">
      <input v-model="action" placeholder="操作（如：审核通过）">
      <input v-model="username" placeholder="操作人">
      <input v-model="keyword" placeholder="详情关键字">
      <button class="btn primary" @click="search">查询</button>
    </div>
    <table class="tbl"><thead><tr><th>时间</th><th>操作人</th><th>操作</th><th>对象类型</th><th>对象</th><th>详情</th></tr></thead>
    <tbody>
      <tr v-for="a in list" :key="a.id">
        <td>{{fmtDT(a.created_at)}}</td><td>{{a.username||'-'}}</td><td>{{a.action}}</td><td>{{a.target_type}}</td><td>{{a.target_id||'-'}}</td><td>{{a.detail}}</td>
      </tr>
      <tr v-if="!list.length"><td colspan="6" class="empty">暂无记录</td></tr>
    </tbody></table>
    <div class="pager">
      <button class="btn sm" :disabled="page<=1" @click="prev">上一页</button>
      <span>第 {{page}} 页 / 共 {{Math.ceil(total/size)}} 页（{{total}} 条）</span>
      <button class="btn sm" :disabled="page*size>=total" @click="next">下一页</button>
    </div>
  </div>`,
};

/* ---------------- 客户档案 ---------------- */
const CustomersView = {
  data: () => ({ list: [], showModal: false, editing: null, form: emptyCustomer(), detail: null, orders: [], keyword: '' }),
  methods: {
    async load() { this.list = await api('/api/customers' + (this.keyword ? '?keyword=' + encodeURIComponent(this.keyword) : '')); },
    add() { this.editing = null; this.form = emptyCustomer(); this.showModal = true; },
    edit(c) { this.editing = c; this.form = { ...c }; this.showModal = true; },
    async save() {
      try {
        if (this.editing) await api('/api/customers/' + this.editing.id, 'PUT', this.form);
        else await api('/api/customers', 'POST', this.form);
        this.showModal = false; this.load(); toast('保存成功', 'success');
      } catch (e) { toast(e.message, 'error'); }
    },
    async del(c) { if (confirm('确认删除客户 ' + c.name + '？')) { await api('/api/customers/' + c.id, 'DELETE'); this.load(); } },
    async view(c) { this.detail = c; this.orders = await api('/api/customers/' + c.id + '/orders'); },
    isAdmin() { return state.role === 'admin'; },
    badge, fmtD,
  },
  mounted() { this.load(); },
  template: `
  <div>
    <div class="card">
      <div class="toolbar"><h3 style="flex:1">客户 / 委托单位档案</h3>
        <input v-model="keyword" placeholder="名称/联系人/电话" @keyup.enter="load"><button class="btn primary" @click="load">查询</button>
        <button class="btn primary" @click="add" v-if="isAdmin()">添加客户</button></div>
      <table class="tbl"><thead><tr><th>委托单位</th><th>联系人</th><th>电话</th><th>邮箱</th><th>地址</th><th>操作</th></tr></thead>
      <tbody><tr v-for="c in list" :key="c.id">
        <td>{{c.name}}</td><td>{{c.contact}}</td><td>{{c.phone}}</td><td>{{c.email}}</td><td>{{c.address}}</td>
        <td>
          <button class="btn link" @click="view(c)">历史委托</button>
          <button class="btn link" v-if="isAdmin()" @click="edit(c)">修改</button>
          <button class="btn link" v-if="isAdmin()" @click="del(c)">删除</button>
        </td>
      </tr></tbody></table>
    </div>
    <div class="modal-mask" v-if="detail" @click.self="detail=null">
      <div class="modal" style="width:760px">
        <h3>{{detail.name}} —— 历史委托</h3>
        <table class="tbl"><thead><tr><th>委托编号</th><th>实验编号</th><th>检测项目</th><th>状态</th><th>委托时间</th></tr></thead>
        <tbody><tr v-for="o in orders" :key="o.id">
          <td>{{o.order_no}}</td><td>{{o.experiment_no||'-'}}</td><td>{{o.test_item}}</td>
          <td v-html="badge(o.status)"></td><td>{{fmtD(o.created_at)}}</td>
        </tr><tr v-if="!orders.length"><td colspan="5" class="empty">暂无委托</td></tr></tbody></table>
        <div class="modal-actions"><button class="btn" @click="detail=null">关闭</button></div>
      </div>
    </div>
    <div class="modal-mask" v-if="showModal" @click.self="showModal=false">
      <div class="modal" style="width:560px"><h3>{{editing?'修改客户':'添加客户'}}</h3>
        <div class="form-row">
          <div class="form-group"><label>委托单位名称</label><input v-model="form.name"></div>
          <div class="form-group"><label>联系人</label><input v-model="form.contact"></div>
        </div>
        <div class="form-row">
          <div class="form-group"><label>电话</label><input v-model="form.phone"></div>
          <div class="form-group"><label>邮箱</label><input v-model="form.email"></div>
        </div>
        <div class="form-group"><label>地址</label><input v-model="form.address"></div>
        <div class="form-group"><label>备注</label><textarea v-model="form.remark"></textarea></div>
        <div class="modal-actions"><button class="btn" @click="showModal=false">取消</button><button class="btn primary" @click="save">保存</button></div>
      </div>
    </div>
  </div>`,
};
function emptyCustomer() { return { name: '', contact: '', phone: '', email: '', address: '', remark: '' }; }

/* ---------------- 根组件 ---------------- */
const RootApp = {
  components: {
    LoginPage, PublicPage, MainLayout, Dashboard, OrderNew, OrderQuery, ReviewView,
    SamplesView, ScheduleView, ExperimentStartView, ExperimentTrackView, ExperimentEndView, ReportsView, EquipmentView, BoardsView, HandoverView, UsersView,
    StatisticsView, AuditLogView, CustomersView, TestCaseLibrary,
  },
  data: () => ({ allEq: [], reviewId: null }),
  computed: {
    isProtected() { return !['/orders/new', '/orders/query'].includes(state.route); },
  },
  methods: {
    async loadEq() { try { this.allEq = await api('/api/equipment'); } catch (e) {} },
    roleText,
  },
  mounted() { this.loadEq(); },
  template: `
  <div>
    <login-page v-if="!state.token && isProtected"></login-page>
    <public-page v-else-if="!state.token"></public-page>
    <main-layout v-else></main-layout>
    <div class="toast" :class="state.toast.type" v-if="state.toast.msg">{{state.toast.msg}}</div>
  </div>`,
};

/* ---------------- 路由 ---------------- */
const routes = ['/dashboard', '/orders/new', '/orders/query', '/review', '/samples', '/schedule', '/expstart', '/exptrack', '/expend', '/reports', '/equipment', '/boards', '/handover', '/statistics', '/customers', '/audit', '/users', '/cases'];
function applyRoute() {
  const h = location.hash.slice(1);
  const home = homeRoute(state.role);
  const allowed = ROLE_ROUTES[state.role] || [];
  let target = (h && routes.includes(h)) ? h : home;
  if (!allowed.includes(target)) target = home;
  state.route = target;
}
window.addEventListener('hashchange', applyRoute);
applyRoute();

/* 供组件内使用全局 helper */
const app = createApp(RootApp);

// 全局注册所有组件（否则 MainLayout / PublicPage 模板里的 <dashboard> 等标签解析不到）
const _components = {
  'login-page': LoginPage, 'public-page': PublicPage, 'main-layout': MainLayout,
  'dashboard': Dashboard, 'order-new': OrderNew, 'order-query': OrderQuery,
  'review-view': ReviewView, 'samples-view': SamplesView, 'schedule-view': ScheduleView,
  'exp-start-view': ExperimentStartView, 'exp-track-view': ExperimentTrackView, 'exp-end-view': ExperimentEndView,
  'reports-view': ReportsView, 'equipment-view': EquipmentView,
  'boards-view': BoardsView, 'handover-view': HandoverView, 'users-view': UsersView,
  'statistics-view': StatisticsView, 'customers-view': CustomersView, 'audit-view': AuditLogView,
  'testcase-library': TestCaseLibrary,
};
Object.entries(_components).forEach(([name, comp]) => app.component(name, comp));

app.config.globalProperties.state = state;
app.config.globalProperties.navigate = navigate;
app.config.globalProperties.fmtD = fmtD;
app.config.globalProperties.fmtDT = fmtDT;
app.config.globalProperties.roleText = roleText;
app.mount('#app');
