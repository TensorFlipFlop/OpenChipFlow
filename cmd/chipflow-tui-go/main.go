package main

import (
	"bufio"
	"encoding/base64"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/mattn/go-runewidth"
)

type menuItem struct {
	Key        string
	Kind       string
	Title      string
	Args       []string
	Desc       string
	Selectable bool
}

type formFieldSpec struct {
	Key       string
	LabelKey  string
	Kind      string
	Required  bool
	StatusKey string
	Choices   []string
	Action    string
}

type requestFormState struct {
	Mode            string
	Title           string
	Fields          []formFieldSpec
	Values          map[string]string
	Selected        int
	Editing         bool
	Buffer          string
	Message         string
	CompletionItems []string
	CompletionBase  string
}

type promptEntry struct {
	ID      string
	Label   string
	Path    string
	Content string
}

type overlayItem struct {
	Label   string
	Value   string
	Kind    string
	Enabled bool
}

type runtimeState struct {
	Model   string
	Variant string
}

type localizedText map[string]string

type uiEntry struct {
	Title localizedText `json:"title"`
	Desc  localizedText `json:"desc"`
}

type runnerUI struct {
	DefaultLocale string             `json:"default_locale"`
	Commands      map[string]uiEntry `json:"commands"`
	RequestModes  map[string]uiEntry `json:"request_modes"`
	Flows         map[string]uiEntry `json:"flows"`
	Stages        map[string]uiEntry `json:"stages"`
}

type stageConfig struct {
	Description string `json:"description"`
}

type runnerConfig struct {
	Stages map[string]stageConfig `json:"stages"`
	Flows  map[string][]string    `json:"flows"`
	UI     runnerUI               `json:"ui"`
}

type variantChoice struct {
	Value string `json:"value"`
	Label string `json:"label"`
}

type modelProfile struct {
	Family         string          `json:"family"`
	Label          string          `json:"label"`
	DefaultVariant string          `json:"default_variant"`
	Variants       []variantChoice `json:"variants"`
}

type capabilities struct {
	RuntimeCatalog struct {
		Models        []string                `json:"models"`
		ModelProfiles map[string]modelProfile `json:"model_profiles"`
	} `json:"runtime_catalog"`
}

type lineMsg struct{ Line string }
type doneMsg struct{ RC int }

type model struct {
	root   string
	runner string
	cfg    runnerConfig
	caps   capabilities
	locale string

	width  int
	height int

	allItems []menuItem
	items    []menuItem
	selected int

	dryRun    bool
	running   bool
	logScroll int

	status string
	logs   []string

	logView string // ALL | OUT | ERR | RESULTS | INPUTS | PROMPTS

	paletteActive bool
	paletteFilter string

	quitPresses  int
	quitDeadline time.Time

	overlayMode       string
	overlayItems      []overlayItem
	overlaySel        int
	overlayTextTitle  string
	overlayText       string
	overlayTextScroll int

	formState     *requestFormState
	manualPrompts []promptEntry

	runtime runtimeState

	runCh chan tea.Msg
	cmd   *exec.Cmd
	cmdMu sync.Mutex

	lastBaseArgs      []string
	lastRunnerArgs    []string
	lastTitle         string
	lastCmd           string
	lastRequestPath   string
	lastUIManifest    string
	resultManifest    map[string]any
	currentStage      string
	lastFailedStage   string
	confirmRunnerArgs []string
	confirmTitle      string
}

var manifestLineRE = regexp.MustCompile(`^\[MANIFEST\]\s+(.+)$`)
var stageRunLineRE = regexp.MustCompile(`\[RUN\]\s+([a-zA-Z0-9_]+)\.[a-zA-Z0-9_]+:`)

var uiStrings = map[string]map[string]string{
	"en": {
		"locale.en": "English",
		"locale.zh": "Chinese",

		"title.go":      "OpenChipFlow | / Palette | Enter Open/Run | Ctrl+O/T/S Overlay | v View | l Lang | r Rerun | Ctrl+C x3 Quit",
		"panel.nav":     "NAVIGATION",
		"panel.palette": "PALETTE",
		"panel.output":  "OUTPUT",
		"panel.status":  "STATUS",
		"panel.focus":   "FOCUS",
		"panel.last":    "LAST",
		"panel.outline": "OUTLINE",
		"panel.result":  "RESULTS",
		"panel.request": "INPUTS",
		"pane.form":     "REQUEST FORM",

		"section.modes":    "Modes",
		"section.tools":    "Tools",
		"section.advanced": "Advanced",

		"advanced.direct_flow":             "Direct Flow Run",
		"advanced.direct_flow.desc":        "Bypass request form and run a backend flow directly",
		"advanced.stage_quick_run":         "Stage Quick Run",
		"advanced.stage_quick_run.desc":    "Run one backend stage directly for debugging",
		"advanced.rerun_failed_stage":      "Rerun Failed Stage",
		"advanced.rerun_failed_stage.desc": "Rerun the last failed backend stage directly",

		"mode.spec_flow.title":                "Spec Flow",
		"mode.spec_flow.desc":                 "Start from a spec input and choose plan or all in the form",
		"mode.handoff_intake.title":           "Handoff Intake",
		"mode.handoff_intake.form_title":      "Handoff Intake / Import & Review",
		"mode.handoff_intake.desc":            "Audit raw handoff files and emit a gap report / repair prompt",
		"mode.incremental_verify_ready.title": "Verify-Ready Handoff",
		"mode.incremental_verify_ready.desc":  "Run the verification loop from a verify-ready handoff manifest",

		"mode.spec_flow.stage.precheck":                  "Precheck",
		"mode.spec_flow.stage.plan":                      "Plan",
		"mode.spec_flow.stage.generate":                  "Generate RTL/TB",
		"mode.spec_flow.stage.prepare":                   "Prepare Verification",
		"mode.spec_flow.stage.smoke":                     "Smoke",
		"mode.spec_flow.stage.verify":                    "Verify",
		"mode.spec_flow.stage.regress":                   "Regress",
		"mode.spec_flow.stage.deliver":                   "Deliver",
		"mode.handoff_intake.stage.discover":             "Discover Inputs",
		"mode.handoff_intake.stage.audit":                "Audit Handoff",
		"mode.handoff_intake.stage.feedback":             "Emit Feedback",
		"mode.incremental_verify_ready.stage.validate":   "Validate Handoff",
		"mode.incremental_verify_ready.stage.prepare":    "Prepare Verification",
		"mode.incremental_verify_ready.stage.quality":    "Quality Gates",
		"mode.incremental_verify_ready.stage.smoke":      "Smoke",
		"mode.incremental_verify_ready.stage.verify":     "Verify",
		"mode.incremental_verify_ready.stage.regress":    "Regress",
		"mode.incremental_verify_ready.stage.compliance": "Compliance",
		"outline.spec_flow_depth":                        "Execution depth: plan | all",

		"request.spec_source":                "Spec Source",
		"request.execution_mode":             "Execution Mode",
		"request.spec_import_mode":           "Spec Import Mode",
		"request.handoff_root":               "Handoff Bundle Root",
		"request.handoff_root_import":        "Bundle Import Mode",
		"request.handoff_manifest":           "Existing Handoff Manifest",
		"request.handoff_manifest_import":    "Manifest Import Mode",
		"request.source_requirements_root":   "Source Requirements Folder",
		"request.source_requirements_import": "Source Requirements Import",
		"request.target_state":               "Expected Delivery State",
		"request.semantic_review_mode":       "Content Review Policy",
		"request.backend_policy":             "Backend Policy",
		"label.request.run":                  "Run Request",
		"label.request.cancel":               "Cancel",
		"label.request.preview_requirements": "Preview Intake Contract",
		"label.request.copy_requirements":    "Copy Intake Contract",
		"label.request.mode":                 "Mode",
		"label.request.path":                 "Request Manifest",
		"label.ui.path":                      "UI Manifest",
		"label.request.preview":              "Command Preview",
		"label.form.editing":                 "editing",
		"label.form.idle":                    "idle",
		"label.required":                     "required",
		"label.optional":                     "optional",
		"label.one_of":                       "one of two",
		"label.conditional":                  "conditional",
		"label.defaulted":                    "default",
		"label.none":                         "(none)",
		"label.desc":                         "Desc",
		"label.filter":                       "Filter",
		"label.confirm":                      "Confirm",
		"label.preview":                      "Preview",
		"label.preview_only_result":          "Preview only: commands were not executed.",
		"label.actions":                      "Next Actions",
		"label.matches":                      "Matches",
		"label.selected_value":               "Selected Value",
		"label.more_matches":                 "... (+{count} more)",
		"label.view.logs":                    "LOGS",
		"label.view.out":                     "STDOUT",
		"label.view.err":                     "STDERR",
		"label.view.results":                 "RESULTS",
		"label.view.inputs":                  "INPUTS",
		"label.view.prompts":                 "PROMPTS",
		"label.view.basis":                   "BASIS",
		"label.view.requirements":            "REQUIREMENTS",
		"label.view.review":                  "REVIEW",
		"label.view.feedback":                "FEEDBACK",

		"hint.ready":                           "Select a mode and press Enter to open the form",
		"hint.form":                            "Request form: Enter edit/apply, arrows move, Tab completes path",
		"hint.overlay":                         "Overlay open: Enter apply, Esc cancel",
		"hint.palette":                         "Palette open: supports mode:/tool:/advanced: filters",
		"hint.confirm":                         "Confirm armed: Enter runs, Esc cancels",
		"hint.running":                         "Task running: Ctrl+X stop, Ctrl+C x3 force quit",
		"quick.keys":                           "Keys: / palette | Enter open/run | Shift+D dry-run | Shift+Up/Down scroll | v view | o expand output | y copy active prompt | Ctrl+O/T/S overlay | l lang | r/Shift+F rerun | Ctrl+C x3 quit",
		"label.handoff.source_requirements":    "Source Requirements",
		"label.handoff.source_index":           "Source Index",
		"label.handoff.review_status":          "Review Status",
		"label.handoff.files":                  "Files",
		"label.handoff.path":                   "Path",
		"label.handoff.original":               "Original",
		"label.handoff.unavailable_before_run": "Run Handoff Intake to populate this view.",
		"label.handoff.use_form_requirements":  "Use the form actions to preview/copy the requirements prompt before running.",

		"overlay.help":     "Help",
		"overlay.model":    "Model Select (Ctrl+O)",
		"overlay.variant":  "Variant Select (Ctrl+T)",
		"overlay.flow":     "Direct Flow Run",
		"overlay.stage":    "Stage Quick Run (Ctrl+S)",
		"overlay.actions":  "Enter apply / Esc cancel",
		"overlay.no_flow":  "(no flows available)",
		"overlay.no_stage": "(no stages available)",

		"status.select":                 "Select an item and press Enter",
		"status.language":               "Language switched to: {lang}",
		"status.quit.idle":              "Press Ctrl+C {remain} more time(s) to quit",
		"status.quit.running":           "Press Ctrl+C {remain} more time(s) to force quit; current task will be stopped",
		"status.quit.esc_only":          "Esc closes overlay/palette/confirm only; use Ctrl+C x3 to quit",
		"status.quit.q_only":            "Use Ctrl+C x3 to quit",
		"status.path_base":              "Path base directory: {base}",
		"status.path_complete.none":     "No matching path, base: {base}",
		"status.path_complete.single":   "Path completed",
		"status.path_complete.multi":    "{count} matches: {sample}",
		"status.path_complete.disabled": "Only path fields support completion",
		"status.output_overlay_open":    "Expanded {view} in wide overlay",
		"status.handoff.feedback_open":  "Handoff needs repair; FEEDBACK open (y copy prompt, o expand)",
		"status.handoff.review_open":    "Handoff review loaded; REVIEW open (o expand)",
		"log.ready":                     "Ready. default: dry-run=OFF (Shift+D toggles)",
	},
	"zh": {
		"locale.en": "英文",
		"locale.zh": "中文",

		"title.go":      "OpenChipFlow | / 命令面板 | Enter 打开/执行 | Ctrl+O/T/S 面板 | v 视图 | l 语言 | r 重跑 | Ctrl+C x3 退出",
		"panel.nav":     "导航",
		"panel.palette": "命令面板",
		"panel.output":  "输出",
		"panel.status":  "状态",
		"panel.focus":   "焦点",
		"panel.last":    "上次命令",
		"panel.outline": "流程大纲",
		"panel.result":  "结果",
		"panel.request": "输入",
		"pane.form":     "请求表单",

		"section.modes":    "Modes",
		"section.tools":    "Tools",
		"section.advanced": "Advanced",

		"advanced.direct_flow":             "直接运行 Flow",
		"advanced.direct_flow.desc":        "绕过 request form，直接运行 backend flow",
		"advanced.stage_quick_run":         "阶段快跑",
		"advanced.stage_quick_run.desc":    "直接运行单个 backend stage 进行调试",
		"advanced.rerun_failed_stage":      "重跑失败 Stage",
		"advanced.rerun_failed_stage.desc": "直接重跑上一次失败的 backend stage",

		"mode.spec_flow.title":                "Spec Flow",
		"mode.spec_flow.desc":                 "从 spec 输入起步，并在表单中选择 plan 或 all",
		"mode.handoff_intake.title":           "Handoff Intake",
		"mode.handoff_intake.form_title":      "Handoff Intake / 导入与审核",
		"mode.handoff_intake.desc":            "审计原始 handoff 文件，并输出 gap report / 补料提示",
		"mode.incremental_verify_ready.title": "Verify-Ready Handoff",
		"mode.incremental_verify_ready.desc":  "从 verify-ready handoff manifest 直接进入验证闭环",

		"mode.spec_flow.stage.precheck":                  "前置检查",
		"mode.spec_flow.stage.plan":                      "规划",
		"mode.spec_flow.stage.generate":                  "生成 RTL/TB",
		"mode.spec_flow.stage.prepare":                   "准备验证",
		"mode.spec_flow.stage.smoke":                     "冒烟",
		"mode.spec_flow.stage.verify":                    "验证",
		"mode.spec_flow.stage.regress":                   "回归",
		"mode.spec_flow.stage.deliver":                   "交付",
		"mode.handoff_intake.stage.discover":             "发现输入",
		"mode.handoff_intake.stage.audit":                "审计 Handoff",
		"mode.handoff_intake.stage.feedback":             "输出反馈",
		"mode.incremental_verify_ready.stage.validate":   "校验 Handoff",
		"mode.incremental_verify_ready.stage.prepare":    "准备验证",
		"mode.incremental_verify_ready.stage.quality":    "质量门禁",
		"mode.incremental_verify_ready.stage.smoke":      "冒烟",
		"mode.incremental_verify_ready.stage.verify":     "验证",
		"mode.incremental_verify_ready.stage.regress":    "回归",
		"mode.incremental_verify_ready.stage.compliance": "合规检查",
		"outline.spec_flow_depth":                        "执行深度：plan | all",

		"request.spec_source":                "Spec 文件",
		"request.execution_mode":             "执行模式",
		"request.spec_import_mode":           "Spec 导入方式",
		"request.handoff_root":               "Handoff 交接包目录",
		"request.handoff_root_import":        "交接包导入方式",
		"request.handoff_manifest":           "已有 Handoff Manifest",
		"request.handoff_manifest_import":    "Manifest 导入方式",
		"request.source_requirements_root":   "原始需求目录",
		"request.source_requirements_import": "原始需求目录导入方式",
		"request.target_state":               "期望交付状态",
		"request.semantic_review_mode":       "内容审核策略",
		"request.backend_policy":             "后端策略",
		"label.request.run":                  "运行请求",
		"label.request.cancel":               "取消",
		"label.request.preview_requirements": "预览交接要求",
		"label.request.copy_requirements":    "复制交接要求",
		"label.request.mode":                 "模式",
		"label.request.path":                 "Request Manifest",
		"label.ui.path":                      "UI Manifest",
		"label.request.preview":              "命令预览",
		"label.form.editing":                 "编辑中",
		"label.form.idle":                    "待机",
		"label.required":                     "必填",
		"label.optional":                     "可选",
		"label.one_of":                       "二选一",
		"label.conditional":                  "条件相关",
		"label.defaulted":                    "默认值",
		"label.none":                         "（空）",
		"label.desc":                         "说明",
		"label.filter":                       "过滤",
		"label.confirm":                      "确认",
		"label.preview":                      "预览",
		"label.preview_only_result":          "仅预演：本次没有真正执行命令。",
		"label.actions":                      "下一步动作",
		"label.matches":                      "匹配项",
		"label.selected_value":               "当前值",
		"label.more_matches":                 "...（另外还有 {count} 项）",
		"label.view.logs":                    "日志",
		"label.view.out":                     "标准输出",
		"label.view.err":                     "标准错误",
		"label.view.results":                 "结果",
		"label.view.inputs":                  "输入",
		"label.view.prompts":                 "提示词",
		"label.view.basis":                   "依据",
		"label.view.requirements":            "要求",
		"label.view.review":                  "审核",
		"label.view.feedback":                "回喂",

		"hint.ready":                           "选择一个模式后按 Enter 打开表单",
		"hint.form":                            "表单：Enter 编辑/应用，方向键移动，Tab 补全路径",
		"hint.overlay":                         "面板已打开：Enter 应用，Esc 取消",
		"hint.palette":                         "命令面板已打开：支持 mode:/tool:/advanced: 过滤",
		"hint.confirm":                         "确认已就绪：Enter 执行，Esc 取消",
		"hint.running":                         "任务运行中：Ctrl+X 停止，Ctrl+C x3 强退",
		"quick.keys":                           "快捷键：/ 面板 | Enter 打开/执行 | Shift+D 切 dry-run | Shift+上下滚日志 | v 视图 | o 展开输出 | y 复制当前提示词 | Ctrl+O/T/S 面板 | l 语言 | r/Shift+F 重跑 | Ctrl+C x3 退出",
		"label.handoff.source_requirements":    "原始需求",
		"label.handoff.source_index":           "来源索引",
		"label.handoff.review_status":          "审核状态",
		"label.handoff.files":                  "文件",
		"label.handoff.path":                   "路径",
		"label.handoff.original":               "原始路径",
		"label.handoff.unavailable_before_run": "请先运行 Handoff Intake 以生成该视图内容。",
		"label.handoff.use_form_requirements":  "运行前请使用表单中的预览/复制按钮查看交接要求提示词。",

		"overlay.help":     "帮助",
		"overlay.model":    "模型选择（Ctrl+O）",
		"overlay.variant":  "Variant 选择（Ctrl+T）",
		"overlay.flow":     "直接运行 Flow",
		"overlay.stage":    "阶段快跑（Ctrl+S）",
		"overlay.actions":  "Enter 应用 / Esc 取消",
		"overlay.no_flow":  "（没有可用 flow）",
		"overlay.no_stage": "（没有可用 stage）",

		"status.select":                 "选择条目后按 Enter",
		"status.language":               "语言已切换为：{lang}",
		"status.quit.idle":              "再按 Ctrl+C {remain} 次退出",
		"status.quit.running":           "再按 Ctrl+C {remain} 次强制退出；当前任务会被停止",
		"status.quit.esc_only":          "Esc 只用于关闭面板/命令面板/确认态；退出请按 Ctrl+C 3 次",
		"status.quit.q_only":            "退出请按 Ctrl+C 3 次",
		"status.path_base":              "路径基准目录：{base}",
		"status.path_complete.none":     "没有匹配路径，基准目录：{base}",
		"status.path_complete.single":   "路径已补全",
		"status.path_complete.multi":    "{count} 个匹配：{sample}",
		"status.path_complete.disabled": "只有路径字段支持补全",
		"status.output_overlay_open":    "已用宽视图展开 {view}",
		"status.handoff.feedback_open":  "Handoff 需要补料；已打开回喂视图（y 复制提示词，o 展开）",
		"status.handoff.review_open":    "已打开审核视图（o 展开）",
		"log.ready":                     "就绪。默认：dry-run=OFF（Shift+D 切换）",
	},
}

func normalizeLocale(v string) string {
	raw := strings.ToLower(strings.TrimSpace(v))
	if raw == "zh" || raw == "en" {
		return raw
	}
	return "en"
}

func toggleLocale(v string) string {
	if normalizeLocale(v) == "en" {
		return "zh"
	}
	return "en"
}

func tr(locale, key string) string {
	lang := normalizeLocale(locale)
	if msg := uiStrings[lang][key]; msg != "" {
		return msg
	}
	if msg := uiStrings["en"][key]; msg != "" {
		return msg
	}
	return key
}

func trf(locale, key string, args map[string]string) string {
	out := tr(locale, key)
	for k, v := range args {
		out = strings.ReplaceAll(out, "{"+k+"}", v)
	}
	return out
}

func localizedValue(v localizedText, locale, fallback string) string {
	if v == nil {
		return fallback
	}
	for _, key := range []string{normalizeLocale(locale), "en", "zh"} {
		if val := strings.TrimSpace(v[key]); val != "" {
			return val
		}
	}
	return fallback
}

func loadRunnerConfig(root string) runnerConfig {
	cfgPath := filepath.Join(root, "config", "runner.json")
	b, err := os.ReadFile(cfgPath)
	if err != nil {
		return runnerConfig{}
	}
	var cfg runnerConfig
	if err := json.Unmarshal(b, &cfg); err != nil {
		return runnerConfig{}
	}
	return cfg
}

func defaultLocale(cfg runnerConfig) string {
	return normalizeLocale(cfg.UI.DefaultLocale)
}

func resolveLocale(cfg runnerConfig, cli string) string {
	if cli = strings.TrimSpace(cli); cli != "" {
		return normalizeLocale(cli)
	}
	if env := strings.TrimSpace(os.Getenv("CHIPFLOW_TUI_LANG")); env != "" {
		return normalizeLocale(env)
	}
	return defaultLocale(cfg)
}

func loadCapabilities(root string) capabilities {
	var c capabilities
	p := filepath.Join(root, "artifacts", "capabilities", "capabilities.json")
	b, err := os.ReadFile(p)
	if err != nil {
		return c
	}
	_ = json.Unmarshal(b, &c)
	return c
}

func menuText(entry uiEntry, locale, fallbackTitle, fallbackDesc string) (string, string) {
	return localizedValue(entry.Title, locale, fallbackTitle), localizedValue(entry.Desc, locale, fallbackDesc)
}

func buildModeItems(cfg runnerConfig, locale string) []menuItem {
	items := []menuItem{{
		Key:        "section:modes",
		Kind:       "section",
		Title:      tr(locale, "section.modes"),
		Selectable: false,
	}}
	modeUI := cfg.UI.RequestModes
	defs := []struct {
		Key           string
		FallbackTitle string
		FallbackDesc  string
	}{
		{"spec_flow", tr(locale, "mode.spec_flow.title"), tr(locale, "mode.spec_flow.desc")},
		{"handoff_intake", tr(locale, "mode.handoff_intake.title"), tr(locale, "mode.handoff_intake.desc")},
		{"incremental_verify_ready", tr(locale, "mode.incremental_verify_ready.title"), tr(locale, "mode.incremental_verify_ready.desc")},
	}
	for _, def := range defs {
		title, desc := menuText(modeUI[def.Key], locale, def.FallbackTitle, def.FallbackDesc)
		items = append(items, menuItem{
			Key:        def.Key,
			Kind:       "mode",
			Title:      title,
			Desc:       desc,
			Selectable: true,
		})
	}
	return items
}

func buildToolItems(cfg runnerConfig, locale string) []menuItem {
	items := []menuItem{{
		Key:        "section:tools",
		Kind:       "section",
		Title:      tr(locale, "section.tools"),
		Selectable: false,
	}}
	defs := []struct {
		Key           string
		Args          []string
		FallbackTitle string
		FallbackDesc  string
	}{
		{"doctor", []string{"doctor"}, "Environment Check", "Run precheck diagnostics only"},
		{"list", []string{"list"}, "List Flows / Stages", "List configured flows and stages"},
	}
	for _, def := range defs {
		title, desc := menuText(cfg.UI.Commands[def.Key], locale, def.FallbackTitle, def.FallbackDesc)
		items = append(items, menuItem{
			Key:        def.Key,
			Kind:       "tool",
			Title:      title,
			Desc:       desc,
			Args:       def.Args,
			Selectable: true,
		})
	}
	return items
}

func buildAdvancedItems(locale string) []menuItem {
	return []menuItem{
		{
			Key:        "section:advanced",
			Kind:       "section",
			Title:      tr(locale, "section.advanced"),
			Selectable: false,
		},
		{
			Key:        "advanced.direct_flow",
			Kind:       "advanced",
			Title:      tr(locale, "advanced.direct_flow"),
			Desc:       tr(locale, "advanced.direct_flow.desc"),
			Args:       []string{"direct_flow"},
			Selectable: true,
		},
		{
			Key:        "advanced.stage_quick_run",
			Kind:       "advanced",
			Title:      tr(locale, "advanced.stage_quick_run"),
			Desc:       tr(locale, "advanced.stage_quick_run.desc"),
			Args:       []string{"stage_quick_run"},
			Selectable: true,
		},
		{
			Key:        "advanced.rerun_failed_stage",
			Kind:       "advanced",
			Title:      tr(locale, "advanced.rerun_failed_stage"),
			Desc:       tr(locale, "advanced.rerun_failed_stage.desc"),
			Args:       []string{"rerun_failed_stage"},
			Selectable: true,
		},
	}
}

func buildMenuItems(cfg runnerConfig, locale string) []menuItem {
	var items []menuItem
	items = append(items, buildModeItems(cfg, locale)...)
	items = append(items, buildToolItems(cfg, locale)...)
	items = append(items, buildAdvancedItems(locale)...)
	return items
}

func loadItems(root, locale string) []menuItem {
	cfg := loadRunnerConfig(root)
	return buildMenuItems(cfg, locale)
}

func firstSelectableIndex(items []menuItem) int {
	for i, it := range items {
		if it.Selectable {
			return i
		}
	}
	return 0
}

func nextSelectableIndex(items []menuItem, current, step int) int {
	if len(items) == 0 {
		return 0
	}
	idx := current
	for i := 0; i < len(items); i++ {
		idx = (idx + step + len(items)) % len(items)
		if items[idx].Selectable {
			return idx
		}
	}
	return current
}

func filterMenuItems(all []menuItem, raw string) []menuItem {
	q := strings.TrimSpace(strings.ToLower(raw))
	selectable := make([]menuItem, 0, len(all))
	for _, it := range all {
		if it.Selectable {
			selectable = append(selectable, it)
		}
	}
	if q == "" {
		return selectable
	}
	if strings.HasPrefix(q, "mode:") || strings.HasPrefix(q, "request:") {
		key := strings.TrimSpace(strings.SplitN(q, ":", 2)[1])
		out := []menuItem{}
		for _, it := range selectable {
			if it.Kind == "mode" && strings.Contains(strings.ToLower(it.Key), key) {
				out = append(out, it)
			}
		}
		return out
	}
	if strings.HasPrefix(q, "tool:") {
		key := strings.TrimSpace(strings.SplitN(q, ":", 2)[1])
		out := []menuItem{}
		for _, it := range selectable {
			if it.Kind == "tool" && strings.Contains(strings.ToLower(it.Key), key) {
				out = append(out, it)
			}
		}
		return out
	}
	if strings.HasPrefix(q, "advanced:") || strings.HasPrefix(q, "flow:") {
		key := strings.TrimSpace(strings.SplitN(q, ":", 2)[1])
		out := []menuItem{}
		for _, it := range selectable {
			if it.Kind == "advanced" && strings.Contains(strings.ToLower(it.Key), key) {
				out = append(out, it)
			}
		}
		return out
	}
	out := []menuItem{}
	for _, it := range selectable {
		hay := strings.ToLower(it.Title + " " + it.Desc + " " + it.Key)
		if strings.Contains(hay, q) {
			out = append(out, it)
		}
	}
	return out
}

func modeStageLines(locale, modeKey string) []string {
	type pair struct {
		Key string
	}
	meta := map[string][]string{
		"spec_flow": {
			tr(locale, "outline.spec_flow_depth"),
			"  - " + tr(locale, "mode.spec_flow.stage.precheck"),
			"  - " + tr(locale, "mode.spec_flow.stage.plan"),
			"  - " + tr(locale, "mode.spec_flow.stage.generate"),
			"  - " + tr(locale, "mode.spec_flow.stage.prepare"),
			"  - " + tr(locale, "mode.spec_flow.stage.smoke"),
			"  - " + tr(locale, "mode.spec_flow.stage.verify"),
			"  - " + tr(locale, "mode.spec_flow.stage.regress"),
			"  - " + tr(locale, "mode.spec_flow.stage.deliver"),
		},
		"handoff_intake": {
			"  - " + tr(locale, "mode.handoff_intake.stage.discover"),
			"  - " + tr(locale, "mode.handoff_intake.stage.audit"),
			"  - " + tr(locale, "mode.handoff_intake.stage.feedback"),
		},
		"incremental_verify_ready": {
			"  - " + tr(locale, "mode.incremental_verify_ready.stage.validate"),
			"  - " + tr(locale, "mode.incremental_verify_ready.stage.prepare"),
			"  - " + tr(locale, "mode.incremental_verify_ready.stage.quality"),
			"  - " + tr(locale, "mode.incremental_verify_ready.stage.smoke"),
			"  - " + tr(locale, "mode.incremental_verify_ready.stage.verify"),
			"  - " + tr(locale, "mode.incremental_verify_ready.stage.regress"),
			"  - " + tr(locale, "mode.incremental_verify_ready.stage.compliance"),
		},
	}
	return meta[modeKey]
}

func buildFlowOverlayItems(cfg runnerConfig, locale string) []overlayItem {
	order := []string{"plan", "all", "handoff_intake", "incremental_verify_ready"}
	items := []overlayItem{}
	for _, flow := range order {
		if _, ok := cfg.Flows[flow]; !ok {
			continue
		}
		title, _ := menuText(cfg.UI.Flows[flow], locale, flow, flow)
		items = append(items, overlayItem{Label: title, Value: flow, Kind: "flow", Enabled: true})
	}
	if len(items) == 0 {
		items = append(items, overlayItem{Label: tr(locale, "overlay.no_flow"), Kind: "flow", Enabled: false})
	}
	return items
}

func buildStageOverlayItems(cfg runnerConfig, locale string) []overlayItem {
	stageNames := make([]string, 0, len(cfg.Stages))
	for stage := range cfg.Stages {
		stageNames = append(stageNames, stage)
	}
	sort.Strings(stageNames)
	items := []overlayItem{}
	for _, stage := range stageNames {
		title, _ := menuText(cfg.UI.Stages[stage], locale, stage, cfg.Stages[stage].Description)
		items = append(items, overlayItem{Label: title, Value: stage, Kind: "stage", Enabled: true})
	}
	if len(items) == 0 {
		items = append(items, overlayItem{Label: tr(locale, "overlay.no_stage"), Kind: "stage", Enabled: false})
	}
	return items
}

func runtimeModelProfile(c capabilities, name string) (modelProfile, bool) {
	if strings.TrimSpace(name) == "" {
		return modelProfile{}, false
	}
	prof, ok := c.RuntimeCatalog.ModelProfiles[name]
	return prof, ok
}

func defaultVariantForModel(c capabilities, name string) string {
	prof, ok := runtimeModelProfile(c, name)
	if !ok {
		return ""
	}
	return strings.TrimSpace(prof.DefaultVariant)
}

func displayVariantLabel(c capabilities, modelName, variant string) string {
	prof, ok := runtimeModelProfile(c, modelName)
	if !ok {
		if strings.TrimSpace(variant) != "" {
			return variant
		}
		return "default"
	}
	if len(prof.Variants) == 0 {
		return "n/a"
	}
	target := strings.TrimSpace(variant)
	if target == "" {
		target = strings.TrimSpace(prof.DefaultVariant)
	}
	for _, item := range prof.Variants {
		if strings.TrimSpace(item.Value) == target {
			label := strings.TrimSpace(item.Label)
			if label != "" {
				return label
			}
			return target
		}
	}
	if target != "" {
		return target
	}
	return "default"
}

func buildModelOverlay(c capabilities) []overlayItem {
	items := []overlayItem{{Label: "<default>", Value: "", Kind: "model", Enabled: true}}
	seen := map[string]bool{}
	ordered := make([]string, 0, len(c.RuntimeCatalog.Models))
	for _, m := range c.RuntimeCatalog.Models {
		m = strings.TrimSpace(m)
		if m != "" && !seen[m] {
			seen[m] = true
			ordered = append(ordered, m)
		}
	}
	for _, m := range ordered {
		prof, _ := runtimeModelProfile(c, m)
		label := strings.TrimSpace(prof.Label)
		if label == "" {
			label = m
		}
		if fam := strings.TrimSpace(prof.Family); fam != "" {
			label = fam + ": " + label
		}
		items = append(items, overlayItem{Label: label, Value: m, Kind: "model", Enabled: true})
	}
	if len(items) == 1 {
		items = append(items, overlayItem{Label: "(no selectable models from capability probe)", Kind: "model", Enabled: false})
	}
	return items
}

func buildVariantOverlay(c capabilities, selectedModel string) []overlayItem {
	if strings.TrimSpace(selectedModel) == "" {
		return []overlayItem{{Label: "(select model first)", Kind: "variant", Enabled: false}}
	}
	prof, ok := runtimeModelProfile(c, selectedModel)
	if !ok {
		return []overlayItem{{Label: "(no variant profile for selected model)", Kind: "variant", Enabled: false}}
	}
	if len(prof.Variants) == 0 {
		return []overlayItem{{Label: "(selected model has no separate variant)", Kind: "variant", Enabled: false}}
	}
	def := displayVariantLabel(c, selectedModel, "")
	items := []overlayItem{{Label: "variant: <default=" + def + ">", Value: "", Kind: "variant", Enabled: true}}
	for _, v := range prof.Variants {
		value := strings.TrimSpace(v.Value)
		label := strings.TrimSpace(v.Label)
		if value == "" {
			continue
		}
		if label == "" {
			label = value
		}
		items = append(items, overlayItem{Label: "variant: " + label, Value: value, Kind: "variant", Enabled: true})
	}
	return items
}

func requestModeDefs(locale string) map[string]struct {
	Title  string
	Fields []formFieldSpec
	Values map[string]string
} {
	return map[string]struct {
		Title  string
		Fields []formFieldSpec
		Values map[string]string
	}{
		"spec_flow": {
			Title: tr(locale, "mode.spec_flow.title"),
			Fields: []formFieldSpec{
				{Key: "spec_source", LabelKey: "request.spec_source", Kind: "text", Required: true},
				{Key: "execution_mode", LabelKey: "request.execution_mode", Kind: "choice", Required: true, Choices: []string{"plan", "all"}},
				{Key: "spec_import_mode", LabelKey: "request.spec_import_mode", Kind: "choice", Required: true, Choices: []string{"snapshot", "reference"}},
				{Key: "submit", LabelKey: "label.request.run", Kind: "action", Action: "submit"},
				{Key: "cancel", LabelKey: "label.request.cancel", Kind: "action", Action: "cancel"},
			},
			Values: map[string]string{
				"spec_source":      "",
				"execution_mode":   "plan",
				"spec_import_mode": "snapshot",
			},
		},
		"handoff_intake": {
			Title: tr(locale, "mode.handoff_intake.form_title"),
			Fields: []formFieldSpec{
				{Key: "handoff_root", LabelKey: "request.handoff_root", Kind: "text", StatusKey: "label.one_of"},
				{Key: "handoff_root_import", LabelKey: "request.handoff_root_import", Kind: "choice", StatusKey: "label.defaulted", Choices: []string{"snapshot", "reference"}},
				{Key: "handoff_manifest", LabelKey: "request.handoff_manifest", Kind: "text", StatusKey: "label.one_of"},
				{Key: "handoff_manifest_import", LabelKey: "request.handoff_manifest_import", Kind: "choice", StatusKey: "label.defaulted", Choices: []string{"reference", "snapshot"}},
				{Key: "source_requirements_root", LabelKey: "request.source_requirements_root", Kind: "text", StatusKey: "label.conditional"},
				{Key: "source_requirements_import", LabelKey: "request.source_requirements_import", Kind: "choice", StatusKey: "label.defaulted", Choices: []string{"snapshot", "reference"}},
				{Key: "target_state", LabelKey: "request.target_state", Kind: "choice", StatusKey: "label.defaulted", Choices: []string{"", "analysis_only", "design_ready", "verify_ready"}},
				{Key: "semantic_review_mode", LabelKey: "request.semantic_review_mode", Kind: "choice", StatusKey: "label.defaulted", Choices: []string{"required", "auto", "off"}},
				{Key: "preview_requirements", LabelKey: "label.request.preview_requirements", Kind: "action", Action: "preview_requirements"},
				{Key: "copy_requirements", LabelKey: "label.request.copy_requirements", Kind: "action", Action: "copy_requirements"},
				{Key: "submit", LabelKey: "label.request.run", Kind: "action", Action: "submit"},
				{Key: "cancel", LabelKey: "label.request.cancel", Kind: "action", Action: "cancel"},
			},
			Values: map[string]string{
				"handoff_root":               "",
				"handoff_root_import":        "snapshot",
				"handoff_manifest":           "",
				"handoff_manifest_import":    "reference",
				"source_requirements_root":   "",
				"source_requirements_import": "snapshot",
				"target_state":               "",
				"semantic_review_mode":       "required",
			},
		},
		"incremental_verify_ready": {
			Title: tr(locale, "mode.incremental_verify_ready.title"),
			Fields: []formFieldSpec{
				{Key: "handoff_manifest", LabelKey: "request.handoff_manifest", Kind: "text", Required: true},
				{Key: "handoff_manifest_import", LabelKey: "request.handoff_manifest_import", Kind: "choice", Required: true, Choices: []string{"reference", "snapshot"}},
				{Key: "backend_policy", LabelKey: "request.backend_policy", Kind: "text"},
				{Key: "submit", LabelKey: "label.request.run", Kind: "action", Action: "submit"},
				{Key: "cancel", LabelKey: "label.request.cancel", Kind: "action", Action: "cancel"},
			},
			Values: map[string]string{
				"handoff_manifest":        "",
				"handoff_manifest_import": "reference",
				"backend_policy":          "",
			},
		},
	}
}

func buildRequestForm(locale, mode string) *requestFormState {
	def, ok := requestModeDefs(locale)[mode]
	if !ok {
		return nil
	}
	values := make(map[string]string, len(def.Values))
	for k, v := range def.Values {
		values[k] = v
	}
	return &requestFormState{
		Mode:   mode,
		Title:  def.Title,
		Fields: def.Fields,
		Values: values,
	}
}

func cycleChoice(choices []string, current string, step int) string {
	if len(choices) == 0 {
		return current
	}
	idx := 0
	for i, choice := range choices {
		if choice == current {
			idx = i
			break
		}
	}
	next := (idx + step + len(choices)) % len(choices)
	return choices[next]
}

func isPathField(field formFieldSpec) bool {
	return field.Kind == "text" && (field.Key == "spec_source" || field.Key == "handoff_root" || field.Key == "handoff_manifest" || field.Key == "source_requirements_root")
}

func pathCompletionBase(projectRoot, raw string) (string, string) {
	text := strings.TrimSpace(raw)
	if text == "" {
		return projectRoot, ""
	}
	expanded := expandHome(text)
	if strings.HasSuffix(text, string(os.PathSeparator)) {
		if filepath.IsAbs(expanded) {
			return filepath.Clean(expanded), ""
		}
		return filepath.Clean(filepath.Join(projectRoot, expanded)), ""
	}
	if filepath.IsAbs(expanded) {
		return filepath.Dir(expanded), filepath.Base(expanded)
	}
	base := filepath.Clean(filepath.Join(projectRoot, filepath.Dir(expanded)))
	prefix := filepath.Base(expanded)
	if prefix == "." {
		prefix = ""
	}
	return base, prefix
}

func expandHome(path string) string {
	if !strings.HasPrefix(path, "~") {
		return path
	}
	home, err := os.UserHomeDir()
	if err != nil || home == "" {
		return path
	}
	if path == "~" {
		return home
	}
	return filepath.Join(home, strings.TrimPrefix(path, "~/"))
}

func displayInputPath(projectRoot, original, target string) string {
	raw := strings.TrimSpace(original)
	if strings.HasPrefix(raw, "~") {
		home, err := os.UserHomeDir()
		if err == nil && home != "" {
			if rel, err := filepath.Rel(home, target); err == nil && !strings.HasPrefix(rel, "..") {
				if rel == "." {
					return "~"
				}
				return filepath.ToSlash(filepath.Join("~", rel))
			}
		}
	}
	expanded := expandHome(raw)
	if filepath.IsAbs(expanded) {
		return target
	}
	if rel, err := filepath.Rel(projectRoot, target); err == nil && !strings.HasPrefix(rel, "..") {
		return filepath.ToSlash(rel)
	}
	return target
}

func completePathInput(projectRoot, raw, locale string) (string, string) {
	updated, message, _, _ := completePathInputDetailed(projectRoot, raw, locale)
	return updated, message
}

func completePathInputDetailed(projectRoot, raw, locale string) (string, string, []string, string) {
	baseDir, prefix := pathCompletionBase(projectRoot, raw)
	info, err := os.Stat(baseDir)
	if err != nil || !info.IsDir() {
		return "", trf(locale, "status.path_complete.none", map[string]string{"base": baseDir}), nil, baseDir
	}
	entries, err := os.ReadDir(baseDir)
	if err != nil {
		return "", trf(locale, "status.path_complete.none", map[string]string{"base": baseDir}), nil, baseDir
	}
	sort.Slice(entries, func(i, j int) bool {
		if entries[i].IsDir() != entries[j].IsDir() {
			return entries[i].IsDir()
		}
		return strings.ToLower(entries[i].Name()) < strings.ToLower(entries[j].Name())
	})
	matches := []os.DirEntry{}
	for _, entry := range entries {
		if strings.HasPrefix(entry.Name(), prefix) {
			matches = append(matches, entry)
		}
	}
	if len(matches) == 0 {
		return "", trf(locale, "status.path_complete.none", map[string]string{"base": baseDir}), nil, baseDir
	}
	candidates := make([]string, 0, len(matches))
	for _, entry := range matches {
		target := filepath.Join(baseDir, entry.Name())
		display := displayInputPath(projectRoot, raw, target)
		if entry.IsDir() && !strings.HasSuffix(display, "/") {
			display += "/"
		}
		candidates = append(candidates, display)
	}
	if len(matches) == 1 {
		target := filepath.Join(baseDir, matches[0].Name())
		text := displayInputPath(projectRoot, raw, target)
		if matches[0].IsDir() && !strings.HasSuffix(text, "/") {
			text += "/"
		}
		return text, tr(locale, "status.path_complete.single"), candidates, baseDir
	}
	names := make([]string, 0, len(matches))
	for _, item := range matches {
		names = append(names, item.Name())
	}
	common := commonPrefix(names)
	if common != "" && common != prefix {
		target := filepath.Join(baseDir, common)
		return displayInputPath(projectRoot, raw, target), trf(locale, "status.path_complete.multi", map[string]string{
			"count":  fmt.Sprintf("%d", len(matches)),
			"sample": sampleEntries(matches, min(12, len(matches))),
		}), candidates, baseDir
	}
	return "", trf(locale, "status.path_complete.multi", map[string]string{
		"count":  fmt.Sprintf("%d", len(matches)),
		"sample": sampleEntries(matches, min(12, len(matches))),
	}), candidates, baseDir
}

func commonPrefix(items []string) string {
	if len(items) == 0 {
		return ""
	}
	prefix := items[0]
	for _, item := range items[1:] {
		for !strings.HasPrefix(item, prefix) && prefix != "" {
			prefix = prefix[:len(prefix)-1]
		}
		if prefix == "" {
			return ""
		}
	}
	return prefix
}

func sampleEntries(entries []os.DirEntry, limit int) string {
	if len(entries) < limit {
		limit = len(entries)
	}
	items := make([]string, 0, limit)
	for _, entry := range entries[:limit] {
		name := entry.Name()
		if entry.IsDir() {
			name += "/"
		}
		items = append(items, name)
	}
	return strings.Join(items, ", ")
}

func validateRequestForm(form *requestFormState) string {
	switch form.Mode {
	case "spec_flow":
		if strings.TrimSpace(form.Values["spec_source"]) == "" {
			return "spec_source is required"
		}
	case "handoff_intake":
		if strings.TrimSpace(form.Values["handoff_root"]) == "" && strings.TrimSpace(form.Values["handoff_manifest"]) == "" {
			return "handoff_root or handoff_manifest is required"
		}
	case "incremental_verify_ready":
		if strings.TrimSpace(form.Values["handoff_manifest"]) == "" {
			return "handoff_manifest is required"
		}
	default:
		return "unsupported request mode"
	}
	return ""
}

func createRequestManifestPayload(form *requestFormState, sessionID string, dryRun bool, runtime runtimeState) map[string]any {
	payload := map[string]any{
		"schema_version": "runner_request_manifest/v1",
		"session_id":     sessionID,
		"mode":           form.Mode,
		"execution": map[string]any{
			"dry_run": dryRun,
		},
		"runtime": map[string]any{},
		"inputs":  map[string]any{},
	}
	if runtime.Model != "" {
		payload["runtime"].(map[string]any)["model"] = runtime.Model
	}
	if runtime.Variant != "" {
		payload["runtime"].(map[string]any)["variant"] = runtime.Variant
	}
	values := form.Values
	switch form.Mode {
	case "spec_flow":
		payload["execution"].(map[string]any)["mode"] = values["execution_mode"]
		payload["inputs"].(map[string]any)["spec_source"] = map[string]any{
			"path":        strings.TrimSpace(values["spec_source"]),
			"import_mode": strings.TrimSpace(values["spec_import_mode"]),
			"kind":        "file",
		}
	case "handoff_intake":
		if root := strings.TrimSpace(values["handoff_root"]); root != "" {
			payload["inputs"].(map[string]any)["handoff_root"] = map[string]any{
				"path":        root,
				"import_mode": strings.TrimSpace(values["handoff_root_import"]),
				"kind":        "directory",
			}
		}
		if manifest := strings.TrimSpace(values["handoff_manifest"]); manifest != "" {
			payload["inputs"].(map[string]any)["handoff_manifest"] = map[string]any{
				"path":        manifest,
				"import_mode": strings.TrimSpace(values["handoff_manifest_import"]),
				"kind":        "file",
			}
		}
		if sourceRoot := strings.TrimSpace(values["source_requirements_root"]); sourceRoot != "" {
			payload["inputs"].(map[string]any)["source_requirements_root"] = map[string]any{
				"path":        sourceRoot,
				"import_mode": strings.TrimSpace(values["source_requirements_import"]),
				"kind":        "directory",
			}
		}
		if state := strings.TrimSpace(values["target_state"]); state != "" {
			payload["inputs"].(map[string]any)["target_state"] = state
		}
		if mode := strings.TrimSpace(values["semantic_review_mode"]); mode != "" {
			payload["inputs"].(map[string]any)["semantic_review_mode"] = mode
		}
	case "incremental_verify_ready":
		payload["inputs"].(map[string]any)["handoff_manifest"] = map[string]any{
			"path":        strings.TrimSpace(values["handoff_manifest"]),
			"import_mode": strings.TrimSpace(values["handoff_manifest_import"]),
			"kind":        "file",
		}
		if backend := strings.TrimSpace(values["backend_policy"]); backend != "" {
			payload["inputs"].(map[string]any)["backend_policy"] = backend
		}
	}
	return payload
}

func requestManifestDir(projectRoot, sessionID string) string {
	return filepath.Join(projectRoot, "artifacts", "requests", sessionID)
}

func writeRequestManifest(projectRoot string, payload map[string]any) (string, error) {
	sessionID, _ := payload["session_id"].(string)
	if strings.TrimSpace(sessionID) == "" {
		sessionID = time.Now().Format("tui_session_20060102_150405_000000000")
	}
	dir := requestManifestDir(projectRoot, sessionID)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	out := filepath.Join(dir, "request.form.json")
	body, err := json.MarshalIndent(payload, "", "  ")
	if err != nil {
		return "", err
	}
	if err := os.WriteFile(out, append(body, '\n'), 0o644); err != nil {
		return "", err
	}
	return out, nil
}

func buildRequestRunnerArgs(runner, manifestPath string, runtime runtimeState) []string {
	args := []string{runner, "request", "--request-manifest", manifestPath}
	if runtime.Model != "" {
		args = append(args, "--model", runtime.Model)
	}
	if runtime.Variant != "" {
		args = append(args, "--variant", runtime.Variant)
	}
	return args
}

func parseManifestPath(text string) string {
	payload := strings.TrimSpace(strings.TrimPrefix(strings.TrimPrefix(text, "[O] "), "[E] "))
	m := manifestLineRE.FindStringSubmatch(payload)
	if len(m) != 2 {
		return ""
	}
	return strings.TrimSpace(m[1])
}

func loadUIManifest(path string) map[string]any {
	if strings.TrimSpace(path) == "" {
		return nil
	}
	b, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var out map[string]any
	if err := json.Unmarshal(b, &out); err != nil {
		return nil
	}
	return out
}

func extractSessionIDFromPath(projectRoot, rawPath string) string {
	text := strings.TrimSpace(rawPath)
	if text == "" {
		return ""
	}
	target := expandHome(text)
	if !filepath.IsAbs(target) {
		target = filepath.Join(projectRoot, target)
	}
	abs, err := filepath.Abs(target)
	if err != nil {
		abs = filepath.Clean(target)
	}
	rel, err := filepath.Rel(projectRoot, abs)
	if err != nil {
		return ""
	}
	parts := strings.Split(filepath.ToSlash(rel), "/")
	for idx := 0; idx < len(parts)-2; idx++ {
		if idx+3 < len(parts) && parts[idx] == "cocotb_ex" && parts[idx+1] == "artifacts" && parts[idx+2] == "sessions" {
			return parts[idx+3]
		}
		if parts[idx] == "artifacts" && parts[idx+1] == "sessions" {
			return parts[idx+2]
		}
	}
	return ""
}

func sessionIDHintForForm(projectRoot string, form *requestFormState) string {
	if form == nil {
		return ""
	}
	switch form.Mode {
	case "incremental_verify_ready":
		return extractSessionIDFromPath(projectRoot, form.Values["handoff_manifest"])
	case "handoff_intake":
		for _, key := range []string{"handoff_manifest", "handoff_root"} {
			if hinted := extractSessionIDFromPath(projectRoot, form.Values[key]); hinted != "" {
				return hinted
			}
		}
	}
	return ""
}

func requirementsPromptText(projectRoot, targetState string) string {
	state := strings.TrimSpace(targetState)
	if state == "" {
		state = "verify_ready"
	}
	pythonBin := "python3"
	if _, err := exec.LookPath(pythonBin); err != nil {
		pythonBin = "python"
	}
	cmd := exec.Command(pythonBin, "tools/generate_handoff_requirements_prompt.py", "--target-state", state)
	cmd.Dir = projectRoot
	out, err := cmd.Output()
	if err != nil {
		return fmt.Sprintf("Failed to generate requirements prompt: %v", err)
	}
	return string(out)
}

func promptEntriesFromManifest(manifest map[string]any) []promptEntry {
	if manifest == nil {
		return nil
	}
	artifacts := map[string]map[string]any{}
	for _, item := range asMapSlice(manifest["primary_artifacts"]) {
		id := stringValue(item["id"])
		if id != "" {
			artifacts[id] = item
		}
	}
	out := []promptEntry{}
	for _, def := range []struct {
		ID    string
		Label string
	}{
		{ID: "handoff_requirements_prompt", Label: "handoff_requirements_prompt.txt"},
		{ID: "handoff_contract_repair_prompt", Label: "handoff_contract_repair_prompt.txt"},
		{ID: "handoff_semantic_repair_prompt", Label: "handoff_semantic_repair_prompt.txt"},
		{ID: "handoff_repair_prompt", Label: "handoff_repair_prompt.txt"},
	} {
		item := artifacts[def.ID]
		if item == nil {
			continue
		}
		exists, ok := item["exists"].(bool)
		if ok && !exists {
			continue
		}
		path := stringValue(item["abs_path"])
		if strings.TrimSpace(path) == "" {
			continue
		}
		body, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		out = append(out, promptEntry{ID: def.ID, Label: def.Label, Path: path, Content: string(body)})
	}
	return out
}

func artifactMapFromManifest(manifest map[string]any) map[string]map[string]any {
	out := map[string]map[string]any{}
	if manifest == nil {
		return out
	}
	for _, item := range asMapSlice(manifest["primary_artifacts"]) {
		id := stringValue(item["id"])
		if id != "" {
			out[id] = item
		}
	}
	return out
}

func inputArtifactByName(manifest map[string]any, name string) map[string]any {
	if manifest == nil {
		return nil
	}
	for _, item := range asMapSlice(manifest["input_artifacts"]) {
		if stringValue(item["name"]) == name {
			return item
		}
	}
	return nil
}

func readTextIfExists(path string) string {
	path = strings.TrimSpace(path)
	if path == "" {
		return ""
	}
	body, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	return string(body)
}

func readJSONIfExists(path string) map[string]any {
	raw := readTextIfExists(path)
	if strings.TrimSpace(raw) == "" {
		return nil
	}
	var out map[string]any
	if err := json.Unmarshal([]byte(raw), &out); err != nil {
		return nil
	}
	return out
}

func listReferenceFiles(path string) []string {
	root := strings.TrimSpace(path)
	if root == "" {
		return nil
	}
	items := []string{}
	_ = filepath.WalkDir(root, func(cur string, d os.DirEntry, err error) error {
		if err != nil || d == nil || d.IsDir() {
			return nil
		}
		rel, relErr := filepath.Rel(root, cur)
		if relErr != nil {
			items = append(items, filepath.ToSlash(cur))
		} else {
			items = append(items, filepath.ToSlash(rel))
		}
		if len(items) >= 32 {
			return filepath.SkipAll
		}
		return nil
	})
	sort.Strings(items)
	return items
}

func formOrInputValue(form *requestFormState, manifest map[string]any, key string) (string, string) {
	if manifest != nil {
		if item := inputArtifactByName(manifest, key); item != nil {
			return strings.TrimSpace(nonEmpty(stringValue(item["resolved_path"]), nonEmpty(stringValue(item["abs_path"]), stringValue(item["path"])))), strings.TrimSpace(stringValue(item["original_path"]))
		}
	}
	if form != nil && form.Mode == "handoff_intake" {
		return strings.TrimSpace(form.Values[key]), ""
	}
	return "", ""
}

func activeResultMode(manifest map[string]any, form *requestFormState, current *menuItem) string {
	if form != nil && strings.TrimSpace(form.Mode) != "" {
		return strings.TrimSpace(form.Mode)
	}
	if manifest != nil {
		if mode := strings.TrimSpace(stringValue(manifest["mode"])); mode != "" {
			return mode
		}
	}
	if current != nil && current.Kind == "mode" {
		return current.Key
	}
	return ""
}

func availableResultViews(activeMode string) []string {
	if activeMode == "handoff_intake" {
		return []string{"ALL", "OUT", "ERR", "BASIS", "REQUIREMENTS", "REVIEW", "FEEDBACK"}
	}
	return []string{"ALL", "OUT", "ERR", "RESULTS", "INPUTS", "PROMPTS"}
}

func selectPromptEntry(manifest map[string]any, manual []promptEntry, preferredIDs ...string) *promptEntry {
	entries := manual
	if len(entries) == 0 {
		entries = promptEntriesFromManifest(manifest)
	}
	if len(entries) == 0 {
		return nil
	}
	if len(preferredIDs) > 0 {
		for _, wanted := range preferredIDs {
			for _, entry := range entries {
				if entry.ID == wanted {
					copy := entry
					return &copy
				}
			}
		}
	}
	copy := entries[0]
	return &copy
}

func buildPromptLines(locale string, manifest map[string]any, manual []promptEntry) []string {
	entries := manual
	if len(entries) == 0 {
		entries = promptEntriesFromManifest(manifest)
	}
	if len(entries) == 0 {
		return []string{tr(locale, "label.none")}
	}
	lines := []string{}
	for idx, entry := range entries {
		if idx > 0 {
			lines = append(lines, "", "---", "")
		}
		lines = append(lines, entry.Label+":")
		if strings.TrimSpace(entry.Path) != "" {
			lines = append(lines, "path: "+entry.Path)
		}
		lines = append(lines, "")
		lines = append(lines, strings.Split(strings.TrimRight(entry.Content, "\n"), "\n")...)
	}
	return lines
}

func preferredPromptToCopy(manifest map[string]any, manual []promptEntry) *promptEntry {
	return selectPromptEntry(
		manifest,
		manual,
		"handoff_semantic_repair_prompt",
		"handoff_contract_repair_prompt",
		"handoff_repair_prompt",
		"handoff_requirements_prompt",
	)
}

func copyTextToClipboard(projectRoot, text, label string) string {
	payload := text
	if !strings.HasSuffix(payload, "\n") {
		payload += "\n"
	}
	encoded := base64.StdEncoding.EncodeToString([]byte(payload))
	if tty, err := os.OpenFile("/dev/tty", os.O_WRONLY, 0); err == nil {
		if _, err := fmt.Fprintf(tty, "\033]52;c;%s\a", encoded); err == nil {
			_ = tty.Close()
			return fmt.Sprintf("Copied %s via OSC52", label)
		}
		_ = tty.Close()
	}
	commands := [][]string{}
	if _, err := exec.LookPath("wl-copy"); err == nil {
		commands = append(commands, []string{"wl-copy"})
	}
	if _, err := exec.LookPath("xclip"); err == nil {
		commands = append(commands, []string{"xclip", "-selection", "clipboard"})
	}
	if _, err := exec.LookPath("xsel"); err == nil {
		commands = append(commands, []string{"xsel", "--clipboard", "--input"})
	}
	if _, err := exec.LookPath("pbcopy"); err == nil {
		commands = append(commands, []string{"pbcopy"})
	}
	if _, err := exec.LookPath("clip.exe"); err == nil {
		commands = append(commands, []string{"clip.exe"})
	}
	for _, args := range commands {
		cmd := exec.Command(args[0], args[1:]...)
		cmd.Stdin = strings.NewReader(payload)
		if err := cmd.Run(); err == nil {
			return fmt.Sprintf("Copied %s via %s", label, filepath.Base(args[0]))
		}
	}
	outDir := filepath.Join(projectRoot, "artifacts", "clipboard")
	if err := os.MkdirAll(outDir, 0o755); err != nil {
		return fmt.Sprintf("Clipboard unavailable and fallback directory creation failed: %v", err)
	}
	file, err := os.CreateTemp(outDir, "prompt_*.txt")
	if err != nil {
		return fmt.Sprintf("Clipboard unavailable and fallback file creation failed: %v", err)
	}
	defer file.Close()
	if _, err := file.WriteString(payload); err != nil {
		return fmt.Sprintf("Clipboard unavailable and fallback write failed: %v", err)
	}
	return fmt.Sprintf("Clipboard unavailable; wrote %s to %s", label, file.Name())
}

func buildHandoffBasisLines(locale string, manifest map[string]any, form *requestFormState) []string {
	lines := []string{}
	if manifest != nil {
		lines = append(lines, fmt.Sprintf("%s: mode=%s", tr(locale, "label.view.basis"), stringValue(manifest["mode"])))
		lines = append(lines, fmt.Sprintf("%s: %s", tr(locale, "label.request.path"), nonEmpty(stringValue(manifest["request_manifest"]), tr(locale, "label.none"))))
	} else {
		lines = append(lines, fmt.Sprintf("%s: mode=handoff_intake", tr(locale, "label.view.basis")))
	}
	handoffRoot, handoffRootOriginal := formOrInputValue(form, manifest, "handoff_root")
	handoffManifest, handoffManifestOriginal := formOrInputValue(form, manifest, "handoff_manifest")
	sourceRoot, sourceRootOriginal := formOrInputValue(form, manifest, "source_requirements_root")
	lines = append(lines, "---", "Handoff")
	lines = append(lines, fmt.Sprintf("- handoff_root: %s", nonEmpty(handoffRoot, tr(locale, "label.none"))))
	if handoffRootOriginal != "" {
		lines = append(lines, fmt.Sprintf("  %s: %s", tr(locale, "label.handoff.original"), handoffRootOriginal))
	}
	lines = append(lines, fmt.Sprintf("- handoff_manifest: %s", nonEmpty(handoffManifest, tr(locale, "label.none"))))
	if handoffManifestOriginal != "" {
		lines = append(lines, fmt.Sprintf("  %s: %s", tr(locale, "label.handoff.original"), handoffManifestOriginal))
	}
	lines = append(lines, "---", tr(locale, "label.handoff.source_requirements"))
	lines = append(lines, fmt.Sprintf("%s: %s", tr(locale, "label.handoff.path"), nonEmpty(sourceRoot, tr(locale, "label.none"))))
	if sourceRootOriginal != "" {
		lines = append(lines, fmt.Sprintf("%s: %s", tr(locale, "label.handoff.original"), sourceRootOriginal))
	}
	if files := listReferenceFiles(sourceRoot); len(files) > 0 {
		lines = append(lines, tr(locale, "label.handoff.files")+":")
		for _, item := range files {
			lines = append(lines, "- "+item)
		}
	}
	if item := artifactMapFromManifest(manifest)["handoff_source_index"]; item != nil {
		sourceIndexPath := strings.TrimSpace(stringValue(item["abs_path"]))
		sourceIndex := readJSONIfExists(sourceIndexPath)
		lines = append(lines, "---", tr(locale, "label.handoff.source_index"))
		lines = append(lines, fmt.Sprintf("%s: %s", tr(locale, "label.handoff.path"), nonEmpty(sourceIndexPath, tr(locale, "label.none"))))
		if sourceIndex != nil {
			lines = append(lines, fmt.Sprintf("- semantic_review_mode: %s", nonEmpty(stringValue(sourceIndex["semantic_review_mode"]), tr(locale, "label.none"))))
			lines = append(lines, fmt.Sprintf("- available: %s", nonEmpty(stringValue(sourceIndex["available"]), tr(locale, "label.none"))))
			lines = append(lines, fmt.Sprintf("- reference_docs: %d", len(asMapSlice(sourceIndex["reference_docs"]))))
		}
	}
	return lines
}

func buildHandoffRequirementsLines(locale string, manifest map[string]any, manual []promptEntry, form *requestFormState) []string {
	entry := selectPromptEntry(manifest, manual, "handoff_requirements_prompt")
	if entry == nil {
		if form != nil && form.Mode == "handoff_intake" {
			return []string{tr(locale, "label.handoff.use_form_requirements")}
		}
		return []string{tr(locale, "label.none")}
	}
	return buildPromptLines(locale, manifest, []promptEntry{*entry})
}

func buildHandoffReviewLines(locale string, manifest map[string]any) []string {
	if manifest == nil {
		return []string{tr(locale, "label.handoff.unavailable_before_run")}
	}
	artifacts := artifactMapFromManifest(manifest)
	contractItem := artifacts["handoff_contract_audit"]
	semanticItem := artifacts["handoff_semantic_review"]
	acceptanceItem := artifacts["handoff_acceptance"]
	contract := readJSONIfExists(stringValue(contractItem["abs_path"]))
	semantic := readJSONIfExists(stringValue(semanticItem["abs_path"]))
	acceptance := readJSONIfExists(stringValue(acceptanceItem["abs_path"]))
	lines := []string{tr(locale, "label.handoff.review_status")}
	lines = append(lines, fmt.Sprintf("- contract: %s", nonEmpty(stringValue(contract["status"]), tr(locale, "label.none"))))
	semanticStatus := nonEmpty(stringValue(acceptance["semantic_status"]), nonEmpty(stringValue(semantic["status"]), tr(locale, "label.none")))
	lines = append(lines, fmt.Sprintf("- semantic: %s", semanticStatus))
	lines = append(lines, fmt.Sprintf("- acceptance: %s", nonEmpty(stringValue(acceptance["status"]), tr(locale, "label.none"))))
	if contractItem != nil {
		lines = append(lines, "---", "Contract audit")
		lines = append(lines, fmt.Sprintf("%s: %s", tr(locale, "label.handoff.path"), nonEmpty(stringValue(contractItem["abs_path"]), stringValue(contractItem["path"]))))
		if contract != nil {
			lines = append(lines, fmt.Sprintf("- target_state: %s", nonEmpty(stringValue(contract["target_state"]), tr(locale, "label.none"))))
			lines = append(lines, fmt.Sprintf("- inferred_state: %s", nonEmpty(stringValue(contract["inferred_state"]), tr(locale, "label.none"))))
			lines = append(lines, fmt.Sprintf("- semantic_review_mode: %s", nonEmpty(stringValue(contract["semantic_review_mode"]), tr(locale, "label.none"))))
			lines = append(lines, fmt.Sprintf("- semantic_review_requested: %s", nonEmpty(stringValue(contract["semantic_review_requested"]), tr(locale, "label.none"))))
		}
	}
	if semanticItem != nil {
		lines = append(lines, "---", "Semantic review")
		lines = append(lines, fmt.Sprintf("%s: %s", tr(locale, "label.handoff.path"), nonEmpty(stringValue(semanticItem["abs_path"]), stringValue(semanticItem["path"]))))
		if semantic != nil {
			if summary := strings.TrimSpace(stringValue(semantic["summary"])); summary != "" {
				lines = append(lines, summary)
			}
			if findings := asMapSlice(semantic["findings"]); len(findings) > 0 {
				lines = append(lines, "")
				for _, finding := range findings {
					lines = append(lines, fmt.Sprintf("- [%s] %s: %s", nonEmpty(stringValue(finding["severity"]), "?"), nonEmpty(stringValue(finding["code"]), "?"), stringValue(finding["message"])))
				}
			}
		}
	}
	if acceptanceItem != nil {
		lines = append(lines, "---", "Acceptance")
		lines = append(lines, fmt.Sprintf("%s: %s", tr(locale, "label.handoff.path"), nonEmpty(stringValue(acceptanceItem["abs_path"]), stringValue(acceptanceItem["path"]))))
		if acceptance != nil {
			if reason := strings.TrimSpace(stringValue(acceptance["semantic_reason"])); reason != "" {
				lines = append(lines, "- reason: "+reason)
			}
		}
	}
	return lines
}

func buildHandoffFeedbackLines(locale string, manifest map[string]any, manual []promptEntry) []string {
	entries := manual
	if len(entries) == 0 {
		entries = promptEntriesFromManifest(manifest)
	}
	order := []string{
		"handoff_semantic_repair_prompt",
		"handoff_contract_repair_prompt",
		"handoff_repair_prompt",
	}
	byID := map[string]promptEntry{}
	for _, entry := range entries {
		byID[entry.ID] = entry
	}
	filtered := []promptEntry{}
	for _, id := range order {
		if entry, ok := byID[id]; ok {
			filtered = append(filtered, entry)
		}
	}
	if len(filtered) == 0 {
		return []string{tr(locale, "label.none")}
	}
	return buildPromptLines(locale, manifest, filtered)
}

func recommendedResultViewForManifest(manifest map[string]any) string {
	if manifest == nil || stringValue(manifest["mode"]) != "handoff_intake" {
		return ""
	}
	artifacts := artifactMapFromManifest(manifest)
	acceptance := readJSONIfExists(stringValue(artifacts["handoff_acceptance"]["abs_path"]))
	status := stringValue(acceptance["status"])
	semanticStatus := stringValue(acceptance["semantic_status"])
	if status == "needs_repair" || semanticStatus == "needs_repair" {
		if selectPromptEntry(manifest, nil, "handoff_semantic_repair_prompt", "handoff_contract_repair_prompt", "handoff_repair_prompt") != nil {
			return "FEEDBACK"
		}
		return "REVIEW"
	}
	if status != "" || artifacts["handoff_contract_audit"] != nil || artifacts["handoff_semantic_review"] != nil {
		return "REVIEW"
	}
	if selectPromptEntry(manifest, nil, "handoff_requirements_prompt") != nil {
		return "REQUIREMENTS"
	}
	return ""
}

func shouldAutoSwitchResultView(currentView string) bool {
	switch strings.ToUpper(strings.TrimSpace(currentView)) {
	case "", "ALL", "OUT", "ERR", "RESULTS", "INPUTS", "PROMPTS":
		return true
	default:
		return false
	}
}

func handoffCompletionStatus(locale string, manifest map[string]any) string {
	if manifest == nil || stringValue(manifest["mode"]) != "handoff_intake" {
		return ""
	}
	switch recommendedResultViewForManifest(manifest) {
	case "FEEDBACK":
		return tr(locale, "status.handoff.feedback_open")
	case "REVIEW":
		return tr(locale, "status.handoff.review_open")
	default:
		return ""
	}
}

func resultViewLabel(locale, view, activeMode string) string {
	switch strings.ToUpper(view) {
	case "OUT":
		return tr(locale, "label.view.out")
	case "ERR":
		return tr(locale, "label.view.err")
	case "BASIS":
		return tr(locale, "label.view.basis")
	case "REQUIREMENTS":
		return tr(locale, "label.view.requirements")
	case "REVIEW":
		return tr(locale, "label.view.review")
	case "FEEDBACK":
		return tr(locale, "label.view.feedback")
	case "RESULTS":
		return tr(locale, "label.view.results")
	case "INPUTS":
		return tr(locale, "label.view.inputs")
	case "PROMPTS":
		return tr(locale, "label.view.prompts")
	default:
		return tr(locale, "label.view.logs")
	}
}

func formatArtifactEntry(item map[string]any, resolvedKey string) string {
	label := stringValue(item["label"])
	if label == "" {
		label = stringValue(item["id"])
	}
	if label == "" {
		label = "?"
	}
	target := stringValue(item[resolvedKey])
	if target == "" {
		target = stringValue(item["path"])
	}
	if target == "" {
		target = stringValue(item["resolved_path"])
	}
	if target == "" {
		target = stringValue(item["abs_path"])
	}
	marker := "ok"
	if preview, ok := item["preview_only"].(bool); ok && preview {
		marker = "preview"
	} else if exists, ok := item["exists"].(bool); ok && !exists {
		marker = "missing"
	}
	return fmt.Sprintf("- %s: %s [%s]", label, target, marker)
}

func asMapSlice(v any) []map[string]any {
	raw, ok := v.([]any)
	if !ok {
		return nil
	}
	out := make([]map[string]any, 0, len(raw))
	for _, item := range raw {
		if m, ok := item.(map[string]any); ok {
			out = append(out, m)
		}
	}
	return out
}

func buildResultLines(locale string, manifest map[string]any, view string, manual []promptEntry, activeMode string, form *requestFormState) []string {
	if activeMode == "handoff_intake" {
		switch strings.ToUpper(view) {
		case "BASIS":
			return buildHandoffBasisLines(locale, manifest, form)
		case "REQUIREMENTS":
			return buildHandoffRequirementsLines(locale, manifest, manual, form)
		case "REVIEW":
			return buildHandoffReviewLines(locale, manifest)
		case "FEEDBACK":
			return buildHandoffFeedbackLines(locale, manifest, manual)
		}
	}
	if manifest == nil {
		if strings.ToUpper(view) == "PROMPTS" {
			return buildPromptLines(locale, manifest, manual)
		}
		return []string{tr(locale, "label.none")}
	}
	lines := []string{}
	switch strings.ToUpper(view) {
	case "RESULTS":
		lines = append(lines, fmt.Sprintf("%s: mode=%s rc=%s", tr(locale, "panel.result"), stringValue(manifest["mode"]), stringValue(manifest["rc"])))
		lines = append(lines, "Run ID: "+stringValue(manifest["run_id"]))
		if dryRun, ok := manifest["dry_run"].(bool); ok && dryRun {
			lines = append(lines, tr(locale, "label.preview_only_result"))
		}
		lines = append(lines, "---")
		lines = append(lines, "Primary")
		for _, item := range asMapSlice(manifest["primary_artifacts"]) {
			lines = append(lines, formatArtifactEntry(item, "path"))
		}
		if secondary := asMapSlice(manifest["secondary_artifacts"]); len(secondary) > 0 {
			lines = append(lines, "---")
			lines = append(lines, "Secondary")
			for _, item := range secondary {
				lines = append(lines, formatArtifactEntry(item, "path"))
			}
		}
		if actions := asMapSlice(manifest["next_actions"]); len(actions) > 0 {
			lines = append(lines, "---")
			lines = append(lines, tr(locale, "label.actions"))
			for _, item := range actions {
				lines = append(lines, fmt.Sprintf("- %s: %s", stringValue(item["id"]), stringValue(item["label"])))
			}
		}
	case "INPUTS":
		lines = append(lines, fmt.Sprintf("%s: mode=%s", tr(locale, "panel.request"), stringValue(manifest["mode"])))
		lines = append(lines, fmt.Sprintf("%s: %s", tr(locale, "label.request.path"), nonEmpty(stringValue(manifest["request_manifest"]), tr(locale, "label.none"))))
		lines = append(lines, "---")
		lines = append(lines, "Request artifacts")
		for _, item := range asMapSlice(manifest["request_artifacts"]) {
			lines = append(lines, formatArtifactEntry(item, "path"))
		}
		lines = append(lines, "---")
		lines = append(lines, "Input artifacts")
		for _, item := range asMapSlice(manifest["input_artifacts"]) {
			lines = append(lines, formatArtifactEntry(item, "resolved_path"))
			if original := stringValue(item["original_path"]); original != "" {
				lines = append(lines, "  original: "+original)
			}
		}
	case "PROMPTS":
		return buildPromptLines(locale, manifest, manual)
	default:
		return []string{tr(locale, "label.none")}
	}
	if len(lines) == 0 {
		return []string{tr(locale, "label.none")}
	}
	return lines
}

func stringValue(v any) string {
	switch x := v.(type) {
	case string:
		return x
	case fmt.Stringer:
		return x.String()
	case float64:
		if float64(int64(x)) == x {
			return fmt.Sprintf("%d", int64(x))
		}
		return fmt.Sprintf("%v", x)
	case int:
		return fmt.Sprintf("%d", x)
	case int64:
		return fmt.Sprintf("%d", x)
	default:
		return ""
	}
}

func normalizeLogPayload(line string) string {
	if strings.HasPrefix(line, "[O] ") || strings.HasPrefix(line, "[E] ") {
		return strings.TrimSpace(line[4:])
	}
	return strings.TrimSpace(line)
}

func parseStageFromRunLine(s string) string {
	m := stageRunLineRE.FindStringSubmatch(strings.TrimSpace(s))
	if len(m) == 2 {
		return m[1]
	}
	return ""
}

func buildContextHint(locale string, running, paletteActive bool, overlayMode string, form *requestFormState, confirm []string) string {
	switch {
	case running:
		return tr(locale, "hint.running")
	case form != nil:
		return tr(locale, "hint.form")
	case overlayMode != "":
		return tr(locale, "hint.overlay")
	case paletteActive:
		return tr(locale, "hint.palette")
	case len(confirm) > 0:
		return tr(locale, "hint.confirm")
	default:
		return tr(locale, "hint.ready")
	}
}

type processStreamer struct {
	cmd  []string
	cwd  string
	proc *exec.Cmd
	q    chan tea.Msg
}

func (p *processStreamer) start() error {
	if len(p.cmd) == 0 {
		return fmt.Errorf("empty command")
	}
	cmd := exec.Command("python3", p.cmd...)
	cmd.Dir = p.cwd
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return err
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return err
	}
	if err := cmd.Start(); err != nil {
		return err
	}
	p.proc = cmd
	p.q = make(chan tea.Msg, 256)
	var wg sync.WaitGroup
	pump := func(r io.Reader, prefix string) {
		defer wg.Done()
		scanner := bufio.NewScanner(r)
		for scanner.Scan() {
			p.q <- lineMsg{Line: prefix + scanner.Text()}
		}
	}
	wg.Add(2)
	go pump(stdout, "[O] ")
	go pump(stderr, "[E] ")
	go func() {
		err := cmd.Wait()
		rc := 0
		if err != nil {
			if exitErr, ok := err.(*exec.ExitError); ok {
				rc = exitErr.ExitCode()
			} else {
				rc = 1
			}
		}
		wg.Wait()
		p.q <- doneMsg{RC: rc}
		close(p.q)
	}()
	return nil
}

func waitRunMsg(ch <-chan tea.Msg) tea.Cmd {
	return func() tea.Msg {
		msg, ok := <-ch
		if !ok {
			return nil
		}
		return msg
	}
}

func (m model) Init() tea.Cmd { return nil }

func (m model) clearConfirm() model {
	m.confirmRunnerArgs = nil
	m.confirmTitle = ""
	return m
}

func (m model) resetQuitHint() model {
	m.quitPresses = 0
	m.quitDeadline = time.Time{}
	return m
}

func (m model) armQuit() (model, tea.Cmd) {
	now := time.Now()
	if m.quitDeadline.IsZero() || now.After(m.quitDeadline) {
		m.quitPresses = 0
	}
	m.quitPresses++
	m.quitDeadline = now.Add(2 * time.Second)
	remain := 3 - m.quitPresses
	if remain <= 0 {
		m.cmdMu.Lock()
		if m.cmd != nil && m.cmd.Process != nil {
			_ = m.cmd.Process.Kill()
		}
		m.cmdMu.Unlock()
		m = m.resetQuitHint()
		return m, tea.Quit
	}
	key := "status.quit.idle"
	if m.running {
		key = "status.quit.running"
	}
	m.status = trf(m.locale, key, map[string]string{"remain": fmt.Sprintf("%d", remain)})
	return m, nil
}

func (m model) buildRunnerArgs(args []string) []string {
	runnerArgs := append([]string{m.runner}, args...)
	if m.dryRun {
		runnerArgs = append(runnerArgs, "--dry-run")
	}
	if len(args) > 0 && args[0] != "list" {
		runnerArgs = append(runnerArgs, "--event-stream", "jsonl")
		if m.runtime.Model != "" {
			runnerArgs = append(runnerArgs, "--model", m.runtime.Model)
		}
		if m.runtime.Variant != "" {
			runnerArgs = append(runnerArgs, "--variant", m.runtime.Variant)
		}
	}
	return runnerArgs
}

func (m model) startRunWithRunnerArgs(baseArgs, runnerArgs []string, title string) (model, tea.Cmd) {
	if m.running {
		m.status = "Command is running; wait or press Ctrl+X to stop"
		return m, nil
	}
	ps := &processStreamer{cmd: runnerArgs, cwd: m.root}
	if err := ps.start(); err != nil {
		m.status = "Start failed: " + err.Error()
		return m, nil
	}
	m.cmdMu.Lock()
	m.cmd = ps.proc
	m.cmdMu.Unlock()

	m.runCh = ps.q
	m.running = true
	m.lastBaseArgs = append([]string{}, baseArgs...)
	m.lastRunnerArgs = append([]string{}, runnerArgs...)
	m.lastTitle = title
	m.lastCmd = "python3 " + strings.Join(runnerArgs, " ")
	m.currentStage = ""
	m.resultManifest = nil
	m.lastUIManifest = ""
	m.logScroll = 0
	m = m.clearConfirm()
	m.logs = []string{"[SYS] start: " + m.lastCmd}
	return m, waitRunMsg(m.runCh)
}

func (m model) startRunWithArgs(args []string, title string) (model, tea.Cmd) {
	return m.startRunWithRunnerArgs(args, m.buildRunnerArgs(args), title)
}

func (m model) stopRun() (model, tea.Cmd) {
	if !m.running {
		m.status = "No command is currently running"
		return m, nil
	}
	m.cmdMu.Lock()
	defer m.cmdMu.Unlock()
	if m.cmd != nil && m.cmd.Process != nil {
		_ = m.cmd.Process.Kill()
		m.status = "Stop requested (Ctrl+X)"
	}
	return m, nil
}

func trimLastRune(s string) string {
	r := []rune(s)
	if len(r) == 0 {
		return ""
	}
	return string(r[:len(r)-1])
}

func (m model) applyPaletteFilter() model {
	m.items = filterMenuItems(m.allItems, m.paletteFilter)
	m.selected = firstSelectableIndex(m.items)
	if len(m.items) == 0 {
		m.status = "No matching command; adjust the palette filter"
	} else {
		m.status = "Palette filter: " + nonEmpty(m.paletteFilter, "(empty)")
	}
	m = m.clearConfirm()
	return m
}

func (m model) reloadLocalizedItems() model {
	prevKey := ""
	prevKind := ""
	if len(m.items) > 0 && m.selected >= 0 && m.selected < len(m.items) {
		prevKey = m.items[m.selected].Key
		prevKind = m.items[m.selected].Kind
	}
	m.allItems = buildMenuItems(m.cfg, m.locale)
	if m.paletteActive {
		m.items = filterMenuItems(m.allItems, m.paletteFilter)
	} else {
		m.items = append([]menuItem{}, m.allItems...)
	}
	m.selected = firstSelectableIndex(m.items)
	if prevKey != "" {
		for idx, it := range m.items {
			if it.Key == prevKey && it.Kind == prevKind {
				m.selected = idx
				break
			}
		}
	}
	return m
}

func sameArgs(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func (m model) openOverlay(mode string) model {
	m.overlayMode = mode
	m.overlaySel = 0
	m.overlayText = ""
	m.overlayTextTitle = ""
	m.overlayTextScroll = 0
	switch mode {
	case "help":
		m.overlayItems = nil
	case "model":
		m.overlayItems = buildModelOverlay(m.caps)
	case "variant":
		m.overlayItems = buildVariantOverlay(m.caps, m.runtime.Model)
	case "flow":
		m.overlayItems = buildFlowOverlayItems(m.cfg, m.locale)
	case "stage":
		m.overlayItems = buildStageOverlayItems(m.cfg, m.locale)
	default:
		m.overlayItems = nil
	}
	return m
}

func (m model) overlayTitle() string {
	switch m.overlayMode {
	case "help":
		return tr(m.locale, "overlay.help")
	case "model":
		return tr(m.locale, "overlay.model")
	case "variant":
		return tr(m.locale, "overlay.variant")
	case "flow":
		return tr(m.locale, "overlay.flow")
	case "stage":
		return tr(m.locale, "overlay.stage")
	default:
		return "Overlay"
	}
}

func (m model) renderHelpOverlay(maxWidth int) string {
	lines := []string{
		"Press ? or Esc to close",
		"",
		"/ palette | Enter open/run | v view | o expand output | l language",
		"Ctrl+O model | Ctrl+T variant | Ctrl+S stage",
		"r rerun last | Shift+F rerun failed stage",
		"Shift+D dry-run toggle",
		"Shift+Up/Down scroll output",
		"Ctrl+X stop | Ctrl+C x3 force quit",
	}
	if m.locale == "zh" {
		lines = []string{
			"按 ? 或 Esc 关闭",
			"",
			"/ 命令面板 | Enter 打开/执行 | v 视图 | o 展开输出 | l 语言",
			"Ctrl+O 模型 | Ctrl+T variant | Ctrl+S stage",
			"r 重跑上次 | Shift+F 重跑失败 stage",
			"Shift+D 切换 dry-run",
			"Shift+上下滚动输出",
			"Ctrl+X 停止 | Ctrl+C x3 强退",
		}
	}
	rendered := []string{}
	for _, line := range lines {
		rendered = append(rendered, wrapText(line, maxWidth)...)
	}
	return strings.Join(rendered, "\n")
}

func (m model) filteredLogLines() []string {
	var current *menuItem
	if len(m.items) > 0 && m.selected >= 0 && m.selected < len(m.items) {
		current = &m.items[m.selected]
	}
	activeMode := activeResultMode(m.resultManifest, m.formState, current)
	switch strings.ToUpper(m.logView) {
	case "OUT":
		out := []string{}
		for _, ln := range m.logs {
			if strings.HasPrefix(ln, "[O] ") || strings.HasPrefix(ln, "[SYS] ") {
				out = append(out, ln)
			}
		}
		return out
	case "ERR":
		out := []string{}
		for _, ln := range m.logs {
			if strings.HasPrefix(ln, "[E] ") || strings.HasPrefix(ln, "[SYS] ") {
				out = append(out, ln)
			}
		}
		return out
	case "RESULTS", "INPUTS", "PROMPTS", "BASIS", "REQUIREMENTS", "REVIEW", "FEEDBACK":
		return buildResultLines(m.locale, m.resultManifest, m.logView, m.manualPrompts, activeMode, m.formState)
	default:
		return append([]string{}, m.logs...)
	}
}

func (m model) openCurrentOutputOverlay() model {
	var current *menuItem
	if len(m.items) > 0 && m.selected >= 0 && m.selected < len(m.items) {
		current = &m.items[m.selected]
	}
	activeMode := activeResultMode(m.resultManifest, m.formState, current)
	lines := m.filteredLogLines()
	if len(lines) == 0 {
		m.status = tr(m.locale, "label.none")
		return m
	}
	m.overlayMode = "prompt"
	m.overlayTextTitle = fmt.Sprintf("%s | %s", tr(m.locale, "panel.output"), resultViewLabel(m.locale, m.logView, activeMode))
	m.overlayText = strings.Join(lines, "\n")
	m.overlayTextScroll = 0
	m.status = trf(m.locale, "status.output_overlay_open", map[string]string{
		"view": resultViewLabel(m.locale, m.logView, activeMode),
	})
	return m
}

func sliceVisibleLines(lines []string, keep, scroll int) ([]string, int, int) {
	if keep <= 0 {
		return nil, 0, 0
	}
	total := len(lines)
	maxScroll := max(0, total-keep)
	effectiveScroll := min(max(0, scroll), maxScroll)
	end := max(0, total-effectiveScroll)
	start := max(0, end-keep)
	return lines[start:end], effectiveScroll, maxScroll
}

func (m model) applyOverlaySelection() (model, tea.Cmd) {
	if len(m.overlayItems) == 0 {
		m.overlayMode = ""
		return m, nil
	}
	item := m.overlayItems[m.overlaySel]
	if !item.Enabled {
		m.status = "Option unavailable"
		return m, nil
	}
	switch item.Kind {
	case "model":
		m.runtime.Model = item.Value
		m.runtime.Variant = defaultVariantForModel(m.caps, m.runtime.Model)
		if item.Value == "" {
			m.status = "Model set to: default"
		} else {
			m.status = "Model set to: " + item.Value + " | variant: " + displayVariantLabel(m.caps, m.runtime.Model, m.runtime.Variant)
		}
		m = m.clearConfirm()
		m.overlayMode = ""
		return m, nil
	case "variant":
		m.runtime.Variant = item.Value
		m.status = "Variant set to: " + displayVariantLabel(m.caps, m.runtime.Model, m.runtime.Variant)
		m = m.clearConfirm()
		m.overlayMode = ""
		return m, nil
	case "flow":
		m.overlayMode = ""
		return m.startRunWithArgs([]string{"run", item.Value}, "run "+item.Value)
	case "stage":
		m.overlayMode = ""
		return m.startRunWithArgs([]string{"stage", item.Value}, "stage "+item.Value)
	default:
		m.overlayMode = ""
		return m, nil
	}
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		return m, nil

	case lineMsg:
		m.logs = append(m.logs, msg.Line)
		payload := normalizeLogPayload(msg.Line)
		if stage := parseStageFromRunLine(payload); stage != "" {
			m.currentStage = stage
		}
		if manifestPath := parseManifestPath(msg.Line); manifestPath != "" {
			m.lastUIManifest = manifestPath
			if loaded := loadUIManifest(manifestPath); loaded != nil {
				m.resultManifest = loaded
				m.manualPrompts = nil
				if shouldAutoSwitchResultView(m.logView) {
					if view := recommendedResultViewForManifest(loaded); view != "" {
						m.logView = view
						m.logScroll = 0
					}
				}
				if hint := handoffCompletionStatus(m.locale, loaded); hint != "" {
					m.status = hint
				} else {
					m.status = "Loaded ui manifest: " + filepath.Base(manifestPath)
				}
			}
		}
		if len(m.logs) > 2000 {
			m.logs = m.logs[len(m.logs)-1200:]
		}
		if m.running && m.runCh != nil {
			return m, waitRunMsg(m.runCh)
		}
		return m, nil

	case doneMsg:
		m.running = false
		m.runCh = nil
		if msg.RC == 0 {
			m.status = "SUCCESS"
			m.lastFailedStage = ""
		} else {
			m.lastFailedStage = nonEmpty(m.currentStage, m.lastFailedStage)
			if m.lastFailedStage != "" {
				m.status = fmt.Sprintf("FAILED rc=%d, stage: %s (Shift+F to rerun)", msg.RC, m.lastFailedStage)
			} else {
				m.status = fmt.Sprintf("FAILED rc=%d", msg.RC)
			}
		}
		if shouldAutoSwitchResultView(m.logView) {
			if view := recommendedResultViewForManifest(m.resultManifest); view != "" {
				m.logView = view
				m.logScroll = 0
			}
		}
		if hint := handoffCompletionStatus(m.locale, m.resultManifest); hint != "" {
			if msg.RC == 0 {
				m.status = hint
			} else {
				m.status = m.status + " | " + hint
			}
		}
		m.logs = append(m.logs, fmt.Sprintf("[SYS] command done, rc=%d", msg.RC))
		m.currentStage = ""
		return m, nil

	case tea.KeyMsg:
		k := msg.String()
		if k == "ctrl+c" {
			return m.armQuit()
		}
		if !m.quitDeadline.IsZero() && time.Now().After(m.quitDeadline) {
			m = m.resetQuitHint()
		}
		if k != "ctrl+c" && m.quitPresses > 0 {
			m = m.resetQuitHint()
		}

		if k == "?" {
			if m.overlayMode == "help" {
				m.overlayMode = ""
				m.overlayText = ""
				m.overlayTextTitle = ""
				m.overlayTextScroll = 0
				m = m.clearConfirm()
				m.status = "Overlay closed"
			} else {
				m = m.openOverlay("help")
				m.overlayText = ""
				m.overlayTextTitle = ""
				m.overlayTextScroll = 0
				m = m.clearConfirm()
				m.status = "Help overlay open"
			}
			return m, nil
		}

		if m.overlayMode == "prompt" {
			switch k {
			case "esc":
				m.overlayMode = ""
				m.overlayText = ""
				m.overlayTextTitle = ""
				m.overlayTextScroll = 0
				m.status = "Overlay closed"
				return m, nil
			case "y", "Y":
				m.status = copyTextToClipboard(m.root, m.overlayText, nonEmpty(m.overlayTextTitle, "prompt"))
				return m, nil
			case "up", "k":
				m.overlayTextScroll = max(0, m.overlayTextScroll-3)
				return m, nil
			case "down", "j":
				m.overlayTextScroll += 3
				return m, nil
			case "shift+up":
				m.overlayTextScroll += 3
				return m, nil
			case "shift+down":
				m.overlayTextScroll = max(0, m.overlayTextScroll-3)
				return m, nil
			}
			return m, nil
		}

		if m.formState != nil {
			field := m.formState.Fields[m.formState.Selected]
			if m.formState.Editing {
				switch k {
				case "esc":
					m.formState.Editing = false
					m.formState.Buffer = ""
					m.formState.Message = "Edit cancelled"
					return m, nil
				case "tab":
					if isPathField(field) {
						updated, message, candidates, baseDir := completePathInputDetailed(m.root, m.formState.Buffer, m.locale)
						if updated != "" {
							m.formState.Buffer = updated
						}
						m.formState.Message = message
						m.formState.CompletionItems = candidates
						m.formState.CompletionBase = baseDir
					} else {
						m.formState.Message = tr(m.locale, "status.path_complete.disabled")
						m.formState.CompletionItems = nil
						m.formState.CompletionBase = ""
					}
					return m, nil
				case "enter":
					m.formState.Values[field.Key] = strings.TrimSpace(m.formState.Buffer)
					m.formState.Editing = false
					m.formState.Message = field.Key + " updated"
					m.formState.CompletionItems = nil
					m.formState.CompletionBase = ""
					return m, nil
				case "backspace", "ctrl+h":
					m.formState.Buffer = trimLastRune(m.formState.Buffer)
					return m, nil
				default:
					if msg.Type == tea.KeyRunes {
						m.formState.Buffer += string(msg.Runes)
					}
					return m, nil
				}
			}

			switch k {
			case "esc":
				m.formState = nil
				m.status = "Request form closed"
				return m, nil
			case "up", "k":
				m.formState.Selected = (m.formState.Selected - 1 + len(m.formState.Fields)) % len(m.formState.Fields)
				m.formState.CompletionItems = nil
				m.formState.CompletionBase = ""
				return m, nil
			case "down", "j":
				m.formState.Selected = (m.formState.Selected + 1) % len(m.formState.Fields)
				m.formState.CompletionItems = nil
				m.formState.CompletionBase = ""
				return m, nil
			case "left", "h":
				if field.Kind == "choice" {
					m.formState.Values[field.Key] = cycleChoice(field.Choices, m.formState.Values[field.Key], -1)
				}
				m.formState.CompletionItems = nil
				m.formState.CompletionBase = ""
				return m, nil
			case "right", "l":
				if field.Kind == "choice" {
					m.formState.Values[field.Key] = cycleChoice(field.Choices, m.formState.Values[field.Key], 1)
					m.formState.CompletionItems = nil
					m.formState.CompletionBase = ""
					return m, nil
				}
			case "enter":
				switch field.Kind {
				case "text":
					m.formState.Editing = true
					m.formState.Buffer = m.formState.Values[field.Key]
					if isPathField(field) {
						base, _ := pathCompletionBase(m.root, m.formState.Buffer)
						m.formState.Message = trf(m.locale, "status.path_base", map[string]string{"base": base})
						m.formState.CompletionBase = base
					} else {
						m.formState.Message = "Editing " + field.Key
						m.formState.CompletionBase = ""
					}
					m.formState.CompletionItems = nil
				case "choice":
					m.formState.Values[field.Key] = cycleChoice(field.Choices, m.formState.Values[field.Key], 1)
					m.formState.CompletionItems = nil
					m.formState.CompletionBase = ""
				case "action":
					if field.Action == "cancel" {
						m.formState = nil
						m.status = "Request form cancelled"
						return m, nil
					}
					if field.Action == "preview_requirements" {
						m.overlayMode = "prompt"
						m.overlayTextTitle = tr(m.locale, "label.request.preview_requirements")
						m.overlayText = requirementsPromptText(m.root, m.formState.Values["target_state"])
						m.overlayTextScroll = 0
						m.status = "Intake contract preview open"
						return m, nil
					}
					if field.Action == "copy_requirements" {
						m.status = copyTextToClipboard(
							m.root,
							requirementsPromptText(m.root, m.formState.Values["target_state"]),
							"handoff intake contract",
						)
						return m, nil
					}
					if errMsg := validateRequestForm(m.formState); errMsg != "" {
						m.formState.Message = errMsg
						m.status = errMsg
						return m, nil
					}
					sessionID := sessionIDHintForForm(m.root, m.formState)
					if strings.TrimSpace(sessionID) == "" {
						sessionID = time.Now().Format("tui_20060102_150405_000000000")
					}
					payload := createRequestManifestPayload(m.formState, sessionID, m.dryRun, m.runtime)
					manifestPath, err := writeRequestManifest(m.root, payload)
					if err != nil {
						m.status = "Request manifest write failed: " + err.Error()
						return m, nil
					}
					runnerArgs := buildRequestRunnerArgs(m.runner, manifestPath, m.runtime)
					title := "request " + stringValue(payload["mode"])
					m.lastRequestPath = manifestPath
					m.lastUIManifest = ""
					m.resultManifest = nil
					m.manualPrompts = nil
					m.formState = nil
					updated, cmd := m.startRunWithRunnerArgs([]string{"request", "--request-manifest", manifestPath}, runnerArgs, title)
					updated.logs = append(updated.logs, "[SYS] request manifest: "+manifestPath)
					updated.status = "RUNNING " + title
					return updated, cmd
				}
				return m, nil
			}
			return m, nil
		}

		if m.overlayMode != "" {
			switch k {
			case "esc":
				m.overlayMode = ""
				m.overlayItems = nil
				m.overlaySel = 0
				m.overlayText = ""
				m.overlayTextTitle = ""
				m.overlayTextScroll = 0
				m.status = "Overlay closed"
				return m, nil
			case "up", "k":
				if len(m.overlayItems) > 0 {
					m.overlaySel = (m.overlaySel - 1 + len(m.overlayItems)) % len(m.overlayItems)
				}
				return m, nil
			case "down", "j":
				if len(m.overlayItems) > 0 {
					m.overlaySel = (m.overlaySel + 1) % len(m.overlayItems)
				}
				return m, nil
			case "enter":
				return m.applyOverlaySelection()
			}
			return m, nil
		}

		if m.paletteActive {
			switch k {
			case "esc":
				m.paletteActive = false
				m.paletteFilter = ""
				m.items = append([]menuItem{}, m.allItems...)
				m.selected = firstSelectableIndex(m.items)
				m = m.clearConfirm()
				m.status = "Palette closed"
				return m, nil
			case "backspace", "ctrl+h":
				m.paletteFilter = trimLastRune(m.paletteFilter)
				m = m.applyPaletteFilter()
				return m, nil
			default:
				if msg.Type == tea.KeyRunes {
					m.paletteFilter += string(msg.Runes)
					m = m.applyPaletteFilter()
					return m, nil
				}
			}
		}

		switch k {
		case "q":
			m.status = tr(m.locale, "status.quit.q_only")
			return m, nil
		case "esc":
			if len(m.confirmRunnerArgs) > 0 {
				m = m.clearConfirm()
				m.status = "Confirmation cancelled"
				return m, nil
			}
			m.status = tr(m.locale, "status.quit.esc_only")
			return m, nil
		case "/", "ctrl+k":
			if m.running {
				m.status = "Cannot open palette while a command is running"
				return m, nil
			}
			m.paletteActive = !m.paletteActive
			if m.paletteActive {
				m.paletteFilter = ""
				m.items = filterMenuItems(m.allItems, m.paletteFilter)
				m.selected = firstSelectableIndex(m.items)
				m.status = "Palette open (/ or Ctrl+K, supports mode:/tool:/advanced: filters)"
			} else {
				m.paletteFilter = ""
				m.items = append([]menuItem{}, m.allItems...)
				m.selected = firstSelectableIndex(m.items)
				m.status = "Palette closed"
			}
			m = m.clearConfirm()
			return m, nil
		case "l", "L":
			m.locale = toggleLocale(m.locale)
			m = m.reloadLocalizedItems()
			if m.overlayMode == "flow" {
				m.overlayItems = buildFlowOverlayItems(m.cfg, m.locale)
			} else if m.overlayMode == "stage" {
				m.overlayItems = buildStageOverlayItems(m.cfg, m.locale)
			}
			m.status = trf(m.locale, "status.language", map[string]string{"lang": tr(m.locale, "locale."+m.locale)})
			m = m.clearConfirm()
			return m, nil
		case "up", "k":
			if len(m.items) > 0 {
				m.selected = nextSelectableIndex(m.items, m.selected, -1)
				m = m.clearConfirm()
			}
			return m, nil
		case "down", "j":
			if len(m.items) > 0 {
				m.selected = nextSelectableIndex(m.items, m.selected, 1)
				m = m.clearConfirm()
			}
			return m, nil
		case "v":
			var current *menuItem
			if len(m.items) > 0 && m.selected >= 0 && m.selected < len(m.items) {
				current = &m.items[m.selected]
			}
			order := availableResultViews(activeResultMode(m.resultManifest, m.formState, current))
			idx := 0
			for i, view := range order {
				if m.logView == view {
					idx = i
					break
				}
			}
			m.logView = order[(idx+1)%len(order)]
			m.logScroll = 0
			m.status = "View: " + resultViewLabel(m.locale, m.logView, activeResultMode(m.resultManifest, m.formState, current))
			return m, nil
		case "o", "O":
			if m.formState != nil {
				m.status = "Close the request form before expanding output"
				return m, nil
			}
			if m.overlayMode != "" {
				m.status = "Close the current overlay before expanding output"
				return m, nil
			}
			m = m.openCurrentOutputOverlay()
			return m, nil
		case "y", "Y":
			var current *menuItem
			if len(m.items) > 0 && m.selected >= 0 && m.selected < len(m.items) {
				current = &m.items[m.selected]
			}
			activeMode := activeResultMode(m.resultManifest, m.formState, current)
			var prompt *promptEntry
			if activeMode == "handoff_intake" {
				switch m.logView {
				case "REQUIREMENTS":
					prompt = selectPromptEntry(m.resultManifest, m.manualPrompts, "handoff_requirements_prompt")
					if prompt == nil && m.formState != nil && m.formState.Mode == "handoff_intake" {
						prompt = &promptEntry{
							ID:      "handoff_requirements_prompt",
							Label:   "handoff_requirements_prompt.txt",
							Content: requirementsPromptText(m.root, m.formState.Values["target_state"]),
						}
					}
				case "FEEDBACK":
					prompt = selectPromptEntry(m.resultManifest, m.manualPrompts, "handoff_semantic_repair_prompt", "handoff_contract_repair_prompt", "handoff_repair_prompt")
				default:
					m.status = "Switch to REQUIREMENTS or FEEDBACK view before copying a prompt"
					return m, nil
				}
			} else {
				if m.logView != "PROMPTS" {
					m.status = "Switch to PROMPTS view before copying a prompt"
					return m, nil
				}
				prompt = preferredPromptToCopy(m.resultManifest, m.manualPrompts)
			}
			if prompt == nil {
				m.status = "No prompt content available to copy"
				return m, nil
			}
			m.status = copyTextToClipboard(m.root, prompt.Content, nonEmpty(prompt.Label, "prompt"))
			return m, nil
		case "shift+up":
			m.logScroll += 3
			m.status = fmt.Sprintf("log scroll=+%d", m.logScroll)
			return m, nil
		case "shift+down":
			m.logScroll = max(0, m.logScroll-3)
			if m.logScroll == 0 {
				m.status = "log scroll=bottom"
			} else {
				m.status = fmt.Sprintf("log scroll=+%d", m.logScroll)
			}
			return m, nil
		case "d":
			m.status = "Use Shift+D to toggle dry-run"
			return m, nil
		case "D":
			m.dryRun = !m.dryRun
			m.status = "dry-run=" + ternary(m.dryRun, "ON", "OFF")
			m = m.clearConfirm()
			return m, nil
		case "ctrl+o":
			if m.running {
				m.status = "Cannot switch model while a command is running"
				return m, nil
			}
			m = m.openOverlay("model")
			m.status = "Model overlay open"
			return m, nil
		case "ctrl+t":
			if m.running {
				m.status = "Cannot switch variant while a command is running"
				return m, nil
			}
			m = m.openOverlay("variant")
			if m.runtime.Model == "" {
				m.status = "Select a model before opening variant"
			} else {
				m.status = "Variant overlay open"
			}
			return m, nil
		case "ctrl+s":
			if m.running {
				m.status = "Cannot quick-run a stage while a command is running"
				return m, nil
			}
			m = m.openOverlay("stage")
			m.status = "Stage overlay open"
			return m, nil
		case "x", "ctrl+x":
			return m.stopRun()
		case "c":
			m.logs = []string{"(cleared)"}
			m.logScroll = 0
			m.status = "Output cleared"
			return m, nil
		case "r":
			if len(m.lastRunnerArgs) == 0 {
				m.status = "No previous command to rerun"
				return m, nil
			}
			m = m.clearConfirm()
			return m.startRunWithRunnerArgs(m.lastBaseArgs, m.lastRunnerArgs, m.lastTitle+" (rerun)")
		case "F":
			if m.running {
				m.status = "Cannot rerun failed stage while a command is running"
				return m, nil
			}
			if m.lastFailedStage == "" {
				m.status = "No failed stage available for rerun"
				return m, nil
			}
			m = m.clearConfirm()
			return m.startRunWithArgs([]string{"stage", m.lastFailedStage}, "rerun failed stage "+m.lastFailedStage)
		case "enter":
			if m.running {
				m.status = "Command is running; wait or press Ctrl+X to stop"
				return m, nil
			}
			if len(m.items) == 0 {
				m.status = "No matching command; adjust the palette filter"
				return m, nil
			}
			item := m.items[m.selected]
			switch item.Kind {
			case "mode":
				m.formState = buildRequestForm(m.locale, item.Key)
				m = m.clearConfirm()
				m.status = "Opened request form: " + item.Key
				return m, nil
			case "advanced":
				action := ""
				if len(item.Args) > 0 {
					action = item.Args[0]
				}
				switch action {
				case "direct_flow":
					m = m.openOverlay("flow")
					m.status = "Direct flow overlay open"
				case "stage_quick_run":
					m = m.openOverlay("stage")
					m.status = "Stage overlay open"
				case "rerun_failed_stage":
					if m.lastFailedStage == "" {
						m.status = "No failed stage available for rerun"
						return m, nil
					}
					return m.startRunWithArgs([]string{"stage", m.lastFailedStage}, "rerun failed stage "+m.lastFailedStage)
				}
				return m, nil
			case "tool":
				runnerArgs := m.buildRunnerArgs(item.Args)
				if len(m.confirmRunnerArgs) == 0 {
					m.confirmRunnerArgs = append([]string{}, runnerArgs...)
					m.confirmTitle = item.Title
					m.status = "Confirm armed: press Enter again to execute, Esc cancels"
					return m, nil
				}
				if !sameArgs(m.confirmRunnerArgs, runnerArgs) || m.confirmTitle != item.Title {
					m.confirmRunnerArgs = append([]string{}, runnerArgs...)
					m.confirmTitle = item.Title
					m.status = "Command changed; press Enter again to confirm"
					return m, nil
				}
				m = m.clearConfirm()
				return m.startRunWithRunnerArgs(item.Args, runnerArgs, item.Title)
			}
		}
		return m, nil
	}

	return m, nil
}

func wrapText(text string, width int) []string {
	if width <= 0 {
		return nil
	}
	if text == "" {
		return []string{""}
	}
	lines := []string{}
	for _, block := range strings.Split(text, "\n") {
		if block == "" {
			lines = append(lines, "")
			continue
		}
		current := ""
		currentWidth := 0
		for _, r := range block {
			rw := runewidth.RuneWidth(r)
			if rw <= 0 {
				rw = 1
			}
			if currentWidth+rw > width && current != "" {
				lines = append(lines, current)
				current = string(r)
				currentWidth = rw
				continue
			}
			current += string(r)
			currentWidth += rw
		}
		if current != "" {
			lines = append(lines, current)
		}
	}
	if len(lines) == 0 {
		return []string{""}
	}
	return lines
}

func renderForm(form *requestFormState, locale string, width, height int) string {
	if form == nil {
		return ""
	}
	lines := []string{
		lipgloss.NewStyle().Bold(true).Render(tr(locale, "pane.form") + ": " + form.Title),
		fmt.Sprintf("%s: %s | %s", tr(locale, "label.request.mode"), form.Mode, ternary(form.Editing, tr(locale, "label.form.editing"), tr(locale, "label.form.idle"))),
		"",
	}
	if form.Selected >= 0 && form.Selected < len(form.Fields) {
		field := form.Fields[form.Selected]
		if field.Kind != "action" {
			value := form.Values[field.Key]
			if form.Editing {
				value = form.Buffer
			}
			if strings.TrimSpace(value) == "" {
				value = tr(locale, "label.none")
			}
			lines = append(lines, lipgloss.NewStyle().Bold(true).Render(tr(locale, "label.selected_value")+": "+tr(locale, field.LabelKey)))
			lines = append(lines, wrapText(value, max(8, width-4))...)
			lines = append(lines, "")
		}
	}
	for idx, field := range form.Fields {
		prefix := "  "
		if idx == form.Selected {
			prefix = "> "
		}
		label := tr(locale, field.LabelKey)
		suffix := tr(locale, "label.optional")
		if field.StatusKey != "" {
			suffix = tr(locale, field.StatusKey)
		} else if field.Required {
			suffix = tr(locale, "label.required")
		}
		if field.Kind == "action" {
			lines = append(lines, clipText(prefix+label, width))
			continue
		}
		value := form.Values[field.Key]
		if form.Editing && idx == form.Selected {
			value = form.Buffer
		}
		if strings.TrimSpace(value) == "" {
			value = tr(locale, "label.none")
		}
		lines = append(lines, clipText(fmt.Sprintf("%s%s [%s]: %s", prefix, label, suffix, value), width))
	}
	if len(form.CompletionItems) > 0 {
		lines = append(lines, "", lipgloss.NewStyle().Bold(true).Render(fmt.Sprintf("%s (%d)", tr(locale, "label.matches"), len(form.CompletionItems))))
		if strings.TrimSpace(form.CompletionBase) != "" {
			lines = append(lines, clipText(trf(locale, "status.path_base", map[string]string{"base": form.CompletionBase}), width))
		}
		remaining := max(4, height-len(lines)-4)
		shown := form.CompletionItems
		if len(shown) > remaining {
			shown = shown[:remaining]
		}
		for _, item := range shown {
			lines = append(lines, clipText("  - "+item, width))
		}
		if hidden := len(form.CompletionItems) - len(shown); hidden > 0 {
			lines = append(lines, clipText(trf(locale, "label.more_matches", map[string]string{"count": fmt.Sprintf("%d", hidden)}), width))
		}
	}
	lines = append(lines, "")
	footer := form.Message
	if footer == "" {
		footer = tr(locale, "hint.form")
	}
	lines = append(lines, wrapText(footer, max(8, width))...)
	return strings.Join(lines, "\n")
}

func renderOverlay(m model, width int) string {
	if m.overlayMode == "" {
		return ""
	}
	if m.overlayMode == "help" {
		return m.renderHelpOverlay(width)
	}
	if m.overlayMode == "prompt" {
		lines := []string{lipgloss.NewStyle().Bold(true).Render(nonEmpty(m.overlayTextTitle, tr(m.locale, "label.view.prompts"))), ""}
		lines = append(lines, wrapText(m.overlayText, max(8, width))...)
		start := min(max(0, m.overlayTextScroll), max(0, len(lines)-1))
		return strings.Join(lines[start:], "\n")
	}
	lines := []string{}
	for idx, item := range m.overlayItems {
		prefix := "  "
		if idx == m.overlaySel {
			prefix = "> "
		}
		line := clipText(prefix+item.Label, width)
		if !item.Enabled {
			line = lipgloss.NewStyle().Faint(true).Render(line)
		}
		lines = append(lines, line)
	}
	lines = append(lines, "")
	lines = append(lines, clipText(tr(m.locale, "overlay.actions"), width))
	return strings.Join(lines, "\n")
}

func renderRightPanel(m model, width, height int) string {
	var current *menuItem
	if len(m.items) > 0 && m.selected >= 0 && m.selected < len(m.items) {
		current = &m.items[m.selected]
	}
	activeMode := activeResultMode(m.resultManifest, m.formState, current)
	title := fmt.Sprintf("%s [%s]", tr(m.locale, "panel.output"), resultViewLabel(m.locale, m.logView, activeMode))
	lines := []string{lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("39")).Render(title), ""}
	if m.overlayMode != "" {
		lines = append(lines, renderOverlay(m, width-4))
		return trimPanelLines(strings.Join(lines, "\n"), height)
	}
	if m.formState != nil {
		lines = append(lines, renderForm(m.formState, m.locale, width-4, height-2))
		return trimPanelLines(strings.Join(lines, "\n"), height)
	}
	visible := m.filteredLogLines()
	if len(visible) == 0 {
		visible = []string{tr(m.locale, "label.none")}
	}
	wrappedVisible := make([]string, 0, len(visible))
	for _, line := range visible {
		wrappedVisible = append(wrappedVisible, wrapText(line, max(8, width-4))...)
	}
	keep := max(1, height-2)
	visible, effectiveScroll, _ := sliceVisibleLines(wrappedVisible, keep, m.logScroll)
	if effectiveScroll > 0 {
		lines[0] = lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("39")).Render(
			fmt.Sprintf("%s [%s] [scroll=%d]", tr(m.locale, "panel.output"), resultViewLabel(m.locale, m.logView, activeMode), effectiveScroll),
		)
	}
	for _, line := range visible {
		lines = append(lines, line)
	}
	return trimPanelLines(strings.Join(lines, "\n"), height)
}

func renderMiddlePanel(m model, width, height int) string {
	var current *menuItem
	if len(m.items) > 0 && m.selected >= 0 && m.selected < len(m.items) {
		current = &m.items[m.selected]
	}
	activeMode := activeResultMode(m.resultManifest, m.formState, current)
	lines := []string{
		lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("39")).Render(tr(m.locale, "panel.status")),
	}
	lines = append(lines, wrapText(fmt.Sprintf("Run: %s | Dry: %s | View: %s", ternary(m.running, "RUNNING", "IDLE"), ternary(m.dryRun, "DRY-RUN", "REAL"), resultViewLabel(m.locale, m.logView, activeMode)), max(8, width-4))...)
	lines = append(lines, wrapText(m.status, max(8, width-4))...)
	lines = append(lines,
		"---",
		lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("39")).Render(tr(m.locale, "panel.focus")),
	)
	lines = append(lines, wrapText(buildContextHint(m.locale, m.running, m.paletteActive, m.overlayMode, m.formState, m.confirmRunnerArgs), max(8, width-4))...)
	lines = append(lines,
		"---",
		lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("39")).Render(tr(m.locale, "panel.last")),
	)
	lines = append(lines, wrapText(nonEmpty(m.lastCmd, tr(m.locale, "label.none")), max(8, width-4))...)
	if m.lastRequestPath != "" {
		lines = append(lines, "---", tr(m.locale, "label.request.path"))
		lines = append(lines, wrapText(m.lastRequestPath, max(8, width-4))...)
	}
	if m.lastUIManifest != "" {
		lines = append(lines, "---", tr(m.locale, "label.ui.path"))
		lines = append(lines, wrapText(m.lastUIManifest, max(8, width-4))...)
	}
	if len(m.confirmRunnerArgs) > 0 {
		lines = append(lines, "---", lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("39")).Render(tr(m.locale, "label.confirm")))
		lines = append(lines, wrapText(strings.Join(m.confirmRunnerArgs, " "), max(8, width-4))...)
	}
	if len(m.items) > 0 && m.selected >= 0 && m.selected < len(m.items) {
		current := m.items[m.selected]
		if current.Kind == "mode" {
			lines = append(lines, "---", lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("39")).Render(tr(m.locale, "panel.outline")))
			lines = append(lines, modeStageLines(m.locale, current.Key)...)
		}
	}
	lines = append(lines, "---")
	lines = append(lines, wrapText(tr(m.locale, "quick.keys"), max(8, width-4))...)
	return trimPanelLines(strings.Join(lines, "\n"), height)
}

func (m model) View() string {
	headerStyle := lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("205"))
	panelBox := lipgloss.NewStyle().
		Border(lipgloss.NormalBorder()).
		BorderForeground(lipgloss.Color("240")).
		Padding(0, 1)

	width := 150
	height := 36
	if m.width > 0 {
		width = m.width
	}
	if m.height > 0 {
		height = m.height
	}

	leftW := max(32, width/4)
	midW := max(36, width/4)
	rightW := max(46, width-leftW-midW-4)
	panelH := max(10, height-6)

	leftTitle := tr(m.locale, "panel.nav")
	if m.paletteActive {
		leftTitle = tr(m.locale, "panel.palette")
	}
	leftLines := []string{lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("39")).Render(leftTitle)}
	if m.paletteActive {
		leftLines = append(leftLines, fmt.Sprintf("%s: %s", tr(m.locale, "label.filter"), nonEmpty(m.paletteFilter, tr(m.locale, "label.none"))), "")
	}
	if len(m.items) == 0 {
		leftLines = append(leftLines, tr(m.locale, "label.none"))
	} else {
		for idx, item := range m.items {
			if item.Kind == "section" {
				leftLines = append(leftLines, lipgloss.NewStyle().Bold(true).Underline(true).Render(item.Title))
				continue
			}
			prefix := "  "
			if idx == m.selected {
				prefix = "> "
			}
			line := prefix + item.Title
			if idx == m.selected {
				line = lipgloss.NewStyle().Reverse(true).Render(clipText(line, leftW-4))
			} else if item.Kind == "mode" {
				line = lipgloss.NewStyle().Bold(true).Render(clipText(line, leftW-4))
			} else {
				line = clipText(line, leftW-4)
			}
			leftLines = append(leftLines, line)
		}
		if m.selected >= 0 && m.selected < len(m.items) {
			leftLines = append(leftLines, "", fmt.Sprintf("%s: %s", tr(m.locale, "label.desc"), clipText(m.items[m.selected].Desc, leftW-10)))
		}
	}

	header := headerStyle.Render(clipText(trf(m.locale, "title.go", nil), max(1, width-1)))
	left := panelBox.Width(leftW).Height(panelH).Render(trimPanelLines(strings.Join(leftLines, "\n"), panelH))
	if m.formState != nil || m.overlayMode == "prompt" {
		formW := max(70, width-leftW-3)
		formPanel := panelBox.Width(formW).Height(panelH).Render(renderRightPanel(m, formW, panelH))
		footer := lipgloss.NewStyle().Reverse(true).Render(fmt.Sprintf("[RUN-STATE:%s] [RISK-STATE:DRY=%s] [LOG-STATE:%s] [?:HELP]",
			ternary(m.running, "RUNNING", "IDLE"),
			ternary(m.dryRun, "ON", "OFF"),
			strings.ToUpper(m.logView),
		))
		row := lipgloss.JoinHorizontal(lipgloss.Top, left, formPanel)
		return lipgloss.JoinVertical(lipgloss.Left, header, row, footer)
	}
	middle := panelBox.Width(midW).Height(panelH).Render(renderMiddlePanel(m, midW, panelH))
	right := panelBox.Width(rightW).Height(panelH).Render(renderRightPanel(m, rightW, panelH))

	footer := lipgloss.NewStyle().Reverse(true).Render(fmt.Sprintf("[RUN-STATE:%s] [RISK-STATE:DRY=%s] [LOG-STATE:%s] [?:HELP]",
		ternary(m.running, "RUNNING", "IDLE"),
		ternary(m.dryRun, "ON", "OFF"),
		strings.ToUpper(m.logView),
	))
	row := lipgloss.JoinHorizontal(lipgloss.Top, left, middle, right)
	return lipgloss.JoinVertical(lipgloss.Left, header, row, footer)
}

func clipText(s string, maxLen int) string {
	if maxLen <= 0 {
		return ""
	}
	if runewidth.StringWidth(s) <= maxLen {
		return s
	}
	if maxLen == 1 {
		return "…"
	}
	var b strings.Builder
	w := 0
	for _, r := range s {
		rw := runewidth.RuneWidth(r)
		if w+rw > maxLen-1 {
			break
		}
		b.WriteRune(r)
		w += rw
	}
	b.WriteRune('…')
	return b.String()
}

func trimPanelLines(s string, maxLines int) string {
	if maxLines <= 0 {
		return ""
	}
	lines := strings.Split(s, "\n")
	if len(lines) <= maxLines {
		return s
	}
	if maxLines == 1 {
		return "…"
	}
	out := append([]string{}, lines[:maxLines-1]...)
	out = append(out, "…")
	return strings.Join(out, "\n")
}

func nonEmpty(v, d string) string {
	if strings.TrimSpace(v) == "" {
		return d
	}
	return v
}

func ternary[T any](cond bool, a, b T) T {
	if cond {
		return a
	}
	return b
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func runLogicSnapshot(m *model, scenario, logView string, width, height int) string {
	m.width = width
	m.height = height
	m.logView = strings.ToUpper(logView)
	if m.logView == "" {
		m.logView = "ALL"
	}
	switch strings.ToLower(strings.TrimSpace(scenario)) {
	case "failure", "failed":
		m.logs = append(m.logs,
			"[SYS] start: python3 scripts/runner.py request --request-manifest artifacts/protocol/examples/request_incremental_verify_ready.json",
			"[O] [RUN] trace_matrix_gate: bash",
			"[O] [FAIL] trace_matrix_gate: exit 1",
			"[SYS] command done, rc=1",
		)
		m.status = "FAILED rc=1, stage: trace_matrix_gate (Shift+F to rerun)"
		m.lastFailedStage = "trace_matrix_gate"
	default:
		m.logs = append(m.logs,
			"[SYS] request manifest: artifacts/protocol/examples/request_spec_flow.json",
			"[SYS] start: python3 scripts/runner.py request --request-manifest artifacts/protocol/examples/request_spec_flow.json",
			"[O] [RUN] plan.validate: success",
			"[SYS] command done, rc=0",
		)
		m.status = "SUCCESS"
	}
	return m.View()
}

func runSmokeModel(root, locale string) model {
	cfg := loadRunnerConfig(root)
	items := buildMenuItems(cfg, locale)
	return model{
		root:     root,
		runner:   filepath.Join("scripts", "runner.py"),
		cfg:      cfg,
		caps:     loadCapabilities(root),
		locale:   locale,
		allItems: append([]menuItem{}, items...),
		items:    append([]menuItem{}, items...),
		selected: firstSelectableIndex(items),
		dryRun:   false,
		logView:  "ALL",
		status:   tr(locale, "status.select"),
		logs: []string{
			tr(locale, "log.ready"),
		},
	}
}

func main() {
	root := flag.String("root", ".", "open-chip-flow project root")
	noAlt := flag.Bool("no-alt-screen", false, "disable alt-screen mode")
	lang := flag.String("lang", "", "ui language override (en|zh)")
	snapshotOut := flag.String("snapshot-out", "", "output file for static snapshot")
	snapshotWidth := flag.Int("snapshot-width", 150, "snapshot width")
	snapshotHeight := flag.Int("snapshot-height", 40, "snapshot height")
	snapshotView := flag.String("snapshot-view", "raw", "snapshot view hint (compat only)")
	snapshotLogView := flag.String("snapshot-logview", "all", "snapshot log view")
	snapshotScenario := flag.String("snapshot-scenario", "success", "snapshot scenario")
	flag.Parse()

	absRoot, err := filepath.Abs(*root)
	if err != nil {
		fmt.Fprintln(os.Stderr, "resolve root failed:", err)
		os.Exit(1)
	}

	cfg := loadRunnerConfig(absRoot)
	locale := resolveLocale(cfg, *lang)
	m := runSmokeModel(absRoot, locale)
	_ = snapshotView

	if *snapshotOut != "" {
		out := runLogicSnapshot(&m, *snapshotScenario, *snapshotLogView, *snapshotWidth, *snapshotHeight)
		if err := os.WriteFile(*snapshotOut, []byte(out), 0o644); err != nil {
			fmt.Fprintln(os.Stderr, "failed to write snapshot:", err)
			os.Exit(1)
		}
		return
	}

	p := tea.NewProgram(m)
	if !*noAlt {
		p = tea.NewProgram(m, tea.WithAltScreen())
	}
	if _, err := p.Run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
