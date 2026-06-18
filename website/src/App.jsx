import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  Browser,
  Check,
  CheckCircle,
  GoogleChromeLogo,
  Code,
  Copy,
  Database,
  DownloadSimple,
  GithubLogo,
  Globe,
  HardDrives,
  List,
  LockKey,
  PauseCircle,
  ShieldCheck,
  Sparkle,
  TerminalWindow,
  UploadSimple,
  X,
} from "@phosphor-icons/react";

const GITHUB_URL = "https://github.com/fangsylar-pixel/browser-takeover-bridge";

const copy = {
  zh: {
    nav: {
      features: "产品优势",
      useCases: "使用场景",
      security: "安全",
      install: "安装",
      github: "GitHub",
    },
    hero: {
      eyebrow: "本地优先的 AI 浏览器控制层",
      title: <>不用新浏览器，不用再登录。<em>直接让 AI 开始工作。</em></>,
      body: "Browser Takeover 将本地 AI Agent 连接到你已经登录的 Chrome 与 Edge 标签页。保留真实会话、掌控网站权限，并可靠处理复杂网页工作流。",
      primary: "5 分钟开始使用",
      secondary: "查看工作原理",
      privacy: "桥接仅监听 127.0.0.1",
      browser: "同时支持 Chrome 与 Edge",
    },
    product: {
      label: "LOCAL AI BRIDGE",
      healthy: "运行正常",
      connected: "本地桥接已连接",
      protocol: "协议",
      tabs: "已同步标签",
      heartbeat: "最后心跳",
      safety: "安全控制",
      safetyBody: "随时暂停，并限制 AI 只操作你信任的网站。",
      policy: "网站访问策略",
      trusted: "仅受信任网站",
      current: "当前网站",
      advanced: "高级浏览器控制",
      on: "已开启",
    },
    proof: [
      ["0", "次重复登录"],
      ["2", "类主流浏览器"],
      ["20/20", "自动测试通过"],
      ["200–300ms", "典型快照响应"],
    ],
    outcomes: {
      eyebrow: "客户为什么选择 Browser Takeover",
      title: "少折腾浏览器，多完成真正的工作",
      body: "传统自动化从一个空白浏览器开始。Browser Takeover 从你已经准备好的工作环境开始。",
      items: [
        {
          icon: Browser,
          title: "保留已登录会话",
          body: "直接使用现有标签页、Cookies 与账户状态，不再创建隔离配置文件，也不用反复扫码登录。",
          tag: "更快开始",
        },
        {
          icon: ShieldCheck,
          title: "控制权始终在你手里",
          body: "一键暂停自动化、限制受信任网站，并通过租约避免多个 Agent 同时写入同一标签页。",
          tag: "更可信",
        },
        {
          icon: TerminalWindow,
          title: "真实网页也能可靠执行",
          body: "Shadow DOM、iframe、上传下载、原生输入、完整页面截图和失败恢复都已内置。",
          tag: "更少失败",
        },
      ],
    },
    compare: {
      eyebrow: "工作方式不同",
      title: "你的浏览器已经准备好了，AI 不该从零开始",
      body: "本地桥接把 Agent 接到真实浏览器上下文，同时保留明确的安全边界。",
      old: "传统浏览器自动化",
      oldItems: ["新建浏览器配置", "再次登录所有账户", "丢失正在工作的页面上下文"],
      new: "Browser Takeover",
      newItems: ["接管现有 Chrome / Edge 标签", "继续使用当前登录状态", "本地桥接与可见安全控制"],
    },
    useCases: {
      eyebrow: "面向真实业务",
      title: "一个桥接层，覆盖四类高价值工作流",
      items: [
        {
          icon: UploadSimple,
          title: "内容发布",
          body: "在已登录的内容平台填写文章、上传素材、保存草稿并检查发布状态。",
        },
        {
          icon: Database,
          title: "CRM 与数据录入",
          body: "读取内部系统、更新记录、跨页面核对字段，并保留可验证的执行结果。",
        },
        {
          icon: Globe,
          title: "多网站研究",
          body: "批量读取现有标签页，在登录态仪表盘与公开资料之间快速对比信息。",
        },
        {
          icon: HardDrives,
          title: "企业内部工具",
          body: "支持 Edge、本地部署和受信任网站策略，适合内网后台与团队工作台。",
        },
      ],
    },
    security: {
      eyebrow: "安全不是附加项",
      title: "本地优先，默认可控",
      body: "客户不只需要 Agent 能做事，还需要知道它在哪里做、何时停止，以及失败后发生了什么。",
      points: [
        ["仅限本机", "HTTP 桥接绑定 127.0.0.1，不暴露公共网络服务。"],
        ["网站白名单", "切换到受信任模式后，未授权域名的命令会被直接拒绝。"],
        ["即时暂停", "从扩展弹窗一键停止所有标签页命令。"],
        ["可验证操作", "点击和填写可以等待 URL、文本、元素或字段值证据。"],
      ],
      panelTitle: "安全策略已生效",
      panelItems: [
        "自动化运行中",
        "仅受信任网站",
        "本地桥接已认证",
        "高级控制可独立关闭",
      ],
    },
    install: {
      eyebrow: "开始使用",
      title: "三步连接你的真实浏览器",
      body: "无需改造现有浏览器配置，也无需开放远程调试端口。",
      steps: [
        {
          number: "01",
          title: "下载项目",
          body: "从 GitHub 获取最新版本，并保留 browser-takeover 文件夹。",
          action: "打开 GitHub",
        },
        {
          number: "02",
          title: "加载扩展",
          body: "在 Chrome 或 Edge 的扩展管理页开启开发者模式，选择“加载已解压的扩展”。",
          code: "browser-takeover/extension",
        },
        {
          number: "03",
          title: "启用插件",
          body: "在 Codex 中安装 Browser Takeover 插件，新建会话后即可读取现有标签页。",
          code: "@Browser Takeover 列出我的标签页",
        },
      ],
      cta: "查看完整安装文档",
    },
    developer: {
      eyebrow: "开放集成",
      title: "不只是一个扩展，而是 Agent 的浏览器执行层",
      body: "通过 MCP 工具使用标签页抢占、结构化操作、批量快照、事件等待、上传下载和工作流恢复。",
      codeTitle: "示例工作流",
      code: [
        "list_tabs()",
        "claim_tab(mode: 'interactive')",
        "action(type: 'fill', expect: { value: 'done' })",
        "release_tab()",
      ],
      badges: ["MCP compatible", "MIT licensed", "Chrome + Edge", "Local-first"],
    },
    faq: {
      eyebrow: "常见问题",
      title: "开始前，你可能还想知道",
      items: [
        ["它会把浏览器数据上传到云端吗？", "Browser Takeover 的桥接服务只监听本机 127.0.0.1。页面内容只有在 Agent 为完成任务而读取时才进入对应 Agent 的上下文。"],
        ["它和官方 Codex Chrome 扩展有什么不同？", "Browser Takeover 强调开放协议、Edge 支持、本地诊断、标签抢占、受信任网站策略和可编排工作流，适合开发者与私有化场景。"],
        ["普通 Chrome 或 Edge 需要用调试参数启动吗？", "不需要。伴随扩展可以连接已经打开的普通浏览器标签页；远程调试端口仅是可选的 CDP 模式。"],
        ["能控制复杂网页吗？", "可以。项目支持开放 Shadow DOM、iframe、坐标操作、文件上传、浏览器下载、原生输入和完整页面截图。"],
      ],
    },
    final: {
      eyebrow: "浏览器已经登录，工作可以现在开始",
      title: "把 AI 接到你真正使用的浏览器",
      body: "无需迁移账户，无需重建工作环境。安装 Browser Takeover，让 Agent 从真实上下文开始。",
      primary: "立即安装 0.6.0",
      secondary: "在 GitHub 查看源码",
    },
    footer: {
      desc: "本地优先的开源 AI 浏览器控制桥。",
      product: "产品",
      resources: "资源",
      links: ["产品优势", "安全模型", "安装指南", "更新日志"],
      resourceLinks: ["GitHub", "README", "安全策略", "问题反馈"],
      rights: "MIT License · Built for browser agents",
    },
  },
  en: {
    nav: {
      features: "Why it wins",
      useCases: "Use cases",
      security: "Security",
      install: "Install",
      github: "GitHub",
    },
    hero: {
      eyebrow: "Local-first AI browser control",
      title: <>No new browser. No login loop. <em>Let your AI get to work.</em></>,
      body: "Browser Takeover connects local AI agents to the Chrome and Edge tabs you already use. Keep authenticated sessions, control site access, and automate real-world browser workflows reliably.",
      primary: "Get started in 5 minutes",
      secondary: "See how it works",
      privacy: "Bridge listens only on 127.0.0.1",
      browser: "Works with Chrome and Edge",
    },
    product: {
      label: "LOCAL AI BRIDGE",
      healthy: "HEALTHY",
      connected: "Local bridge connected",
      protocol: "Protocol",
      tabs: "Synced tabs",
      heartbeat: "Last heartbeat",
      safety: "Safety controls",
      safetyBody: "Pause instantly and limit AI access to websites you trust.",
      policy: "Website policy",
      trusted: "Trusted sites only",
      current: "Current website",
      advanced: "Advanced browser control",
      on: "Enabled",
    },
    proof: [
      ["0", "repeat logins"],
      ["2", "major browsers"],
      ["20/20", "automated tests"],
      ["200–300ms", "typical snapshot"],
    ],
    outcomes: {
      eyebrow: "Why customers choose Browser Takeover",
      title: "Less browser setup. More real work completed.",
      body: "Traditional automation starts from an empty browser. Browser Takeover starts from the workspace you already prepared.",
      items: [
        {
          icon: Browser,
          title: "Keep authenticated sessions",
          body: "Use existing tabs, cookies, and account state—without isolated profiles, repeated logins, or QR-code loops.",
          tag: "Start faster",
        },
        {
          icon: ShieldCheck,
          title: "Stay firmly in control",
          body: "Pause automation, restrict trusted sites, and use leases to prevent multiple agents from writing to the same tab.",
          tag: "Build trust",
        },
        {
          icon: TerminalWindow,
          title: "Handle real-world pages",
          body: "Shadow DOM, iframes, uploads, downloads, native input, full-page capture, and recovery are built in.",
          tag: "Fail less",
        },
      ],
    },
    compare: {
      eyebrow: "A different operating model",
      title: "Your browser is already ready. AI should not start over.",
      body: "The local bridge connects agents to real browser context while preserving explicit safety boundaries.",
      old: "Traditional automation",
      oldItems: ["Create a new browser profile", "Log into every account again", "Lose active workspace context"],
      new: "Browser Takeover",
      newItems: ["Take over existing Chrome / Edge tabs", "Keep current authenticated state", "Use a local bridge with visible controls"],
    },
    useCases: {
      eyebrow: "Built for real operations",
      title: "One bridge layer, four high-value workflows",
      items: [
        {
          icon: UploadSimple,
          title: "Content publishing",
          body: "Fill articles, upload assets, save drafts, and verify publishing status in signed-in platforms.",
        },
        {
          icon: Database,
          title: "CRM and data entry",
          body: "Read internal tools, update records, reconcile fields, and preserve evidence of completion.",
        },
        {
          icon: Globe,
          title: "Multi-site research",
          body: "Batch-read existing tabs and compare signed-in dashboards with public information.",
        },
        {
          icon: HardDrives,
          title: "Internal enterprise tools",
          body: "Edge support, local deployment, and trusted-site policies fit intranet back offices and team workbenches.",
        },
      ],
    },
    security: {
      eyebrow: "Security is not an add-on",
      title: "Local-first and visibly controllable",
      body: "Customers need more than an agent that can act. They need to know where it acts, when it stops, and what happened after failure.",
      points: [
        ["Local machine only", "The HTTP bridge binds to 127.0.0.1 and exposes no public network service."],
        ["Trusted-site policy", "When enabled, commands targeting unapproved hostnames are rejected."],
        ["Instant pause", "Stop all tab commands from the extension popup in one click."],
        ["Evidence-based actions", "Clicks and fills can wait for URL, text, element, or field-value proof."],
      ],
      panelTitle: "Safety policy active",
      panelItems: [
        "Automation running",
        "Trusted sites only",
        "Authenticated local bridge",
        "Advanced control can be disabled",
      ],
    },
    install: {
      eyebrow: "Get started",
      title: "Connect your real browser in three steps",
      body: "No browser migration and no remote-debugging port required.",
      steps: [
        {
          number: "01",
          title: "Download the project",
          body: "Get the latest version from GitHub and keep the browser-takeover folder.",
          action: "Open GitHub",
        },
        {
          number: "02",
          title: "Load the extension",
          body: "Open Chrome or Edge extensions, enable Developer mode, and choose “Load unpacked.”",
          code: "browser-takeover/extension",
        },
        {
          number: "03",
          title: "Enable the plugin",
          body: "Install Browser Takeover in Codex, start a fresh thread, and list your existing tabs.",
          code: "@Browser Takeover list my open tabs",
        },
      ],
      cta: "Read the full installation guide",
    },
    developer: {
      eyebrow: "Open integration layer",
      title: "More than an extension: the browser execution layer for agents",
      body: "Use MCP tools for tab claims, structured actions, batch snapshots, event waits, file transfer, and workflow recovery.",
      codeTitle: "Example workflow",
      code: [
        "list_tabs()",
        "claim_tab(mode: 'interactive')",
        "action(type: 'fill', expect: { value: 'done' })",
        "release_tab()",
      ],
      badges: ["MCP compatible", "MIT licensed", "Chrome + Edge", "Local-first"],
    },
    faq: {
      eyebrow: "FAQ",
      title: "A few things worth knowing",
      items: [
        ["Does it upload my browser data to the cloud?", "The Browser Takeover bridge listens only on 127.0.0.1. Page content enters an agent context only when the agent reads it to complete a task."],
        ["How is it different from the official Codex Chrome extension?", "Browser Takeover focuses on an open protocol, Edge support, local diagnostics, tab claims, trusted-site policies, and programmable workflows for developer and private-deployment use cases."],
        ["Do I need to launch Chrome or Edge with debugging flags?", "No. The companion extension connects to ordinary browser tabs that are already open. A remote-debugging port is only needed for the optional CDP mode."],
        ["Can it handle complex web apps?", "Yes. It supports open Shadow DOM, iframes, coordinate actions, file uploads, managed downloads, native input, and true full-page screenshots."],
      ],
    },
    final: {
      eyebrow: "Your browser is signed in. Work can start now.",
      title: "Connect AI to the browser you actually use",
      body: "No account migration. No rebuilt workspace. Install Browser Takeover and let agents begin with real context.",
      primary: "Install 0.6.0",
      secondary: "View source on GitHub",
    },
    footer: {
      desc: "The local-first open-source browser bridge for AI agents.",
      product: "Product",
      resources: "Resources",
      links: ["Why it wins", "Security model", "Install guide", "Changelog"],
      resourceLinks: ["GitHub", "README", "Security policy", "Report an issue"],
      rights: "MIT License · Built for browser agents",
    },
  },
};

function Brand() {
  return (
    <a className="brand" href="#top" aria-label="Browser Takeover">
      <span className="brand-mark"><Browser size={23} weight="duotone" /></span>
      <span>Browser Takeover</span>
    </a>
  );
}

function ProductPreview({ t }) {
  return (
    <div className="product-preview" aria-label="Browser Takeover extension preview">
      <div className="preview-glow preview-glow-one" />
      <div className="preview-glow preview-glow-two" />
      <div className="preview-window">
        <div className="preview-top">
          <div>
            <span className="preview-kicker">{t.label}</span>
            <strong>Browser Takeover</strong>
          </div>
          <span className="live-dot" />
        </div>
        <div className="health-panel">
          <div className="health-title">
            <div>
              <span>{t.healthy}</span>
              <strong>{t.connected}</strong>
            </div>
            <small>v0.6.0</small>
          </div>
          <div className="health-metrics">
            <div><span>{t.protocol}</span><b>V2</b></div>
            <div><span>{t.tabs}</span><b>8</b></div>
            <div><span>{t.heartbeat}</span><b>Now</b></div>
          </div>
        </div>
        <div className="local-note">
          <LockKey size={18} weight="duotone" />
          <span>127.0.0.1 · Local only</span>
        </div>
        <div className="safety-panel">
          <div className="safety-head">
            <div><strong>{t.safety}</strong><span>{t.safetyBody}</span></div>
            <span className="toggle"><i /></span>
          </div>
          <div className="safety-row">
            <span>{t.policy}</span>
            <b>{t.trusted}</b>
          </div>
          <div className="safety-row">
            <span>{t.current}</span>
            <b>github.com</b>
          </div>
          <div className="advanced-row">
            <div><TerminalWindow size={18} /><span>{t.advanced}</span></div>
            <b>{t.on}</b>
          </div>
        </div>
      </div>
      <div className="browser-chip chrome-chip"><GoogleChromeLogo size={18} weight="fill" /> Chrome</div>
      <div className="browser-chip edge-chip"><Globe size={18} weight="duotone" /> Edge</div>
    </div>
  );
}

function SectionHeading({ eyebrow, title, body, align = "left" }) {
  return (
    <div className={`section-heading ${align === "center" ? "center" : ""}`}>
      <span className="eyebrow">{eyebrow}</span>
      <h2>{title}</h2>
      {body && <p>{body}</p>}
    </div>
  );
}

function App() {
  const initialLanguage = useMemo(() => {
    const saved = window.localStorage.getItem("browser-takeover-language");
    if (saved === "zh" || saved === "en") return saved;
    return navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en";
  }, []);
  const [language, setLanguage] = useState(initialLanguage);
  const [menuOpen, setMenuOpen] = useState(false);
  const [openFaq, setOpenFaq] = useState(0);
  const [copiedCode, setCopiedCode] = useState("");
  const t = copy[language];

  useEffect(() => {
    document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
    document.title = language === "zh"
      ? "Browser Takeover｜让 AI 接管你已登录的 Chrome 与 Edge"
      : "Browser Takeover | Local AI control for Chrome and Edge";
    document.querySelector('meta[name="description"]')?.setAttribute(
      "content",
      language === "zh"
        ? "Browser Takeover 通过本地桥接，让 AI 安全接管你已经登录的 Chrome 与 Edge 标签页。"
        : "Browser Takeover connects local AI agents to authenticated Chrome and Edge tabs through a secure local-first bridge.",
    );
    window.localStorage.setItem("browser-takeover-language", language);
  }, [language]);

  const toggleLanguage = () => setLanguage((current) => current === "zh" ? "en" : "zh");
  const scrollTo = (id) => {
    document.querySelector(id)?.scrollIntoView({ behavior: "smooth" });
    setMenuOpen(false);
  };
  const copyText = async (value) => {
    try {
      await navigator.clipboard.writeText(value);
    } catch (_error) {
      const textarea = document.createElement("textarea");
      textarea.value = value;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      textarea.remove();
    }
    setCopiedCode(value);
    setTimeout(() => setCopiedCode((current) => current === value ? "" : current), 1600);
  };

  return (
    <div id="top" className="site-shell">
      <header className="site-header">
        <div className="header-inner">
          <Brand />
          <nav className={menuOpen ? "open" : ""}>
            <button onClick={() => scrollTo("#features")}>{t.nav.features}</button>
            <button onClick={() => scrollTo("#use-cases")}>{t.nav.useCases}</button>
            <button onClick={() => scrollTo("#security")}>{t.nav.security}</button>
            <button onClick={() => scrollTo("#install")}>{t.nav.install}</button>
          </nav>
          <div className="header-actions">
            <button className="language-button" onClick={toggleLanguage}>
              <Globe size={16} /> {language === "zh" ? "EN" : "中文"}
            </button>
            <a className="github-button" href={GITHUB_URL} target="_blank" rel="noreferrer">
              <GithubLogo size={17} weight="fill" /> {t.nav.github}
            </a>
            <button className="menu-button" onClick={() => setMenuOpen(!menuOpen)} aria-label="Menu">
              {menuOpen ? <X size={22} /> : <List size={22} />}
            </button>
          </div>
        </div>
      </header>

      <main>
        <section className="hero-section">
          <div className="hero-grid">
            <div className="hero-copy">
              <div className="hero-eyebrow"><Sparkle size={16} weight="fill" /> {t.hero.eyebrow}</div>
              <h1>{t.hero.title}</h1>
              <p className="hero-body">{t.hero.body}</p>
              <div className="hero-actions">
                <button className="primary-button" onClick={() => scrollTo("#install")}>
                  {t.hero.primary} <ArrowRight size={18} weight="bold" />
                </button>
                <button className="text-button" onClick={() => scrollTo("#comparison")}>
                  {t.hero.secondary}
                </button>
              </div>
              <div className="hero-trust">
                <span><ShieldCheck size={18} weight="duotone" /> {t.hero.privacy}</span>
                <span><Browser size={18} weight="duotone" /> {t.hero.browser}</span>
              </div>
            </div>
            <ProductPreview t={t.product} />
          </div>
        </section>

        <section className="proof-strip">
          {t.proof.map(([value, label]) => (
            <div key={label}><strong>{value}</strong><span>{label}</span></div>
          ))}
        </section>

        <section id="features" className="section outcomes-section">
          <SectionHeading {...t.outcomes} align="center" />
          <div className="outcome-grid">
            {t.outcomes.items.map((item) => {
              const Icon = item.icon;
              return (
                <article className="outcome" key={item.title}>
                  <div className="icon-box"><Icon size={27} weight="duotone" /></div>
                  <span className="outcome-tag">{item.tag}</span>
                  <h3>{item.title}</h3>
                  <p>{item.body}</p>
                </article>
              );
            })}
          </div>
        </section>

        <section id="comparison" className="section comparison-section">
          <div className="comparison-copy">
            <SectionHeading {...t.compare} />
            <div className="comparison-lists">
              <div className="comparison-list old">
                <strong>{t.compare.old}</strong>
                {t.compare.oldItems.map((item) => <span key={item}><X size={16} weight="bold" />{item}</span>)}
              </div>
              <div className="comparison-list new">
                <strong>{t.compare.new}</strong>
                {t.compare.newItems.map((item) => <span key={item}><Check size={16} weight="bold" />{item}</span>)}
              </div>
            </div>
          </div>
          <div className="comparison-visual">
            <img src="/browser-takeover-comparison.svg" alt="Traditional browser automation compared with Browser Takeover" />
          </div>
        </section>

        <section id="use-cases" className="section use-cases-section">
          <SectionHeading {...t.useCases} />
          <div className="use-case-list">
            {t.useCases.items.map((item, index) => {
              const Icon = item.icon;
              return (
                <article key={item.title}>
                  <span className="use-case-number">0{index + 1}</span>
                  <div className="use-case-icon"><Icon size={24} weight="duotone" /></div>
                  <div><h3>{item.title}</h3><p>{item.body}</p></div>
                  <ArrowRight size={18} />
                </article>
              );
            })}
          </div>
        </section>

        <section id="security" className="security-section">
          <div className="security-inner">
            <div>
              <SectionHeading {...t.security} />
              <div className="security-points">
                {t.security.points.map(([title, body]) => (
                  <div key={title}>
                    <CheckCircle size={22} weight="fill" />
                    <div><strong>{title}</strong><span>{body}</span></div>
                  </div>
                ))}
              </div>
            </div>
            <aside className="security-console">
              <div className="console-top">
                <ShieldCheck size={24} weight="duotone" />
                <strong>{t.security.panelTitle}</strong>
                <span />
              </div>
              {t.security.panelItems.map((item, index) => (
                <div className="console-row" key={item}>
                  <span className={`console-status ${index === 1 ? "restricted" : ""}`}><Check size={13} weight="bold" /></span>
                  <span>{item}</span>
                  <b>{index === 1 ? "4 hosts" : "OK"}</b>
                </div>
              ))}
              <div className="console-footer"><LockKey size={16} /> localhost:17321</div>
            </aside>
          </div>
        </section>

        <section id="install" className="section install-section">
          <SectionHeading {...t.install} align="center" />
          <div className="steps">
            {t.install.steps.map((step) => (
              <article className="step" key={step.number}>
                <span className="step-number">{step.number}</span>
                <h3>{step.title}</h3>
                <p>{step.body}</p>
                {step.action && (
                  <a href={GITHUB_URL} target="_blank" rel="noreferrer">
                    <GithubLogo size={17} /> {step.action}
                  </a>
                )}
                {step.code && (
                  <button
                    className="code-copy"
                    onClick={() => copyText(step.code)}
                    title="Copy"
                    aria-label={copiedCode === step.code ? `Copied ${step.code}` : step.code}
                  >
                    <code>{step.code}</code>
                    {copiedCode === step.code ? <Check size={15} weight="bold" /> : <Copy size={15} />}
                  </button>
                )}
              </article>
            ))}
          </div>
          <a className="docs-link" href={`${GITHUB_URL}#install-the-extension`} target="_blank" rel="noreferrer">
            {t.install.cta} <ArrowRight size={17} />
          </a>
        </section>

        <section className="section developer-section">
          <div className="developer-copy">
            <SectionHeading {...t.developer} />
            <div className="developer-badges">
              {t.developer.badges.map((badge) => <span key={badge}>{badge}</span>)}
            </div>
          </div>
          <div className="code-window">
            <div className="code-title">
              <span><i /><i /><i /></span>
              <b>{t.developer.codeTitle}</b>
              <Code size={18} />
            </div>
            <pre>{t.developer.code.map((line, index) => (
              <code key={line}><span>{String(index + 1).padStart(2, "0")}</span>{line}</code>
            ))}</pre>
          </div>
        </section>

        <section className="section faq-section">
          <SectionHeading {...t.faq} align="center" />
          <div className="faq-list">
            {t.faq.items.map(([question, answer], index) => (
              <article className={openFaq === index ? "open" : ""} key={question}>
                <button onClick={() => setOpenFaq(openFaq === index ? -1 : index)}>
                  <span>{question}</span><b>{openFaq === index ? "−" : "+"}</b>
                </button>
                <div><p>{answer}</p></div>
              </article>
            ))}
          </div>
        </section>

        <section className="final-cta">
          <div>
            <span className="eyebrow">{t.final.eyebrow}</span>
            <h2>{t.final.title}</h2>
            <p>{t.final.body}</p>
          </div>
          <div className="final-actions">
            <a className="primary-button light" href={GITHUB_URL} target="_blank" rel="noreferrer">
              <DownloadSimple size={19} weight="bold" /> {t.final.primary}
            </a>
            <a className="outline-button" href={GITHUB_URL} target="_blank" rel="noreferrer">
              <GithubLogo size={19} weight="fill" /> {t.final.secondary}
            </a>
          </div>
        </section>
      </main>

      <footer>
        <div className="footer-grid">
          <div><Brand /><p>{t.footer.desc}</p></div>
          <div>
            <strong>{t.footer.product}</strong>
            {t.footer.links.map((item, index) => (
              <a href={["#features", "#security", "#install", `${GITHUB_URL}/blob/main/CHANGELOG.md`][index]} key={item}>{item}</a>
            ))}
          </div>
          <div>
            <strong>{t.footer.resources}</strong>
            {t.footer.resourceLinks.map((item, index) => (
              <a
                href={[GITHUB_URL, `${GITHUB_URL}#readme`, `${GITHUB_URL}/blob/main/SECURITY.md`, `${GITHUB_URL}/issues`][index]}
                target="_blank"
                rel="noreferrer"
                key={item}
              >
                {item}
              </a>
            ))}
          </div>
        </div>
        <div className="footer-bottom"><span>© 2026 Browser Takeover</span><span>{t.footer.rights}</span></div>
      </footer>
    </div>
  );
}

export { App };
