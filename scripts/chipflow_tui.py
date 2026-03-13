#!/usr/bin/env python3
"""Terminal TUI for chipflow (opencode-like command workflow).

Features:
- Left command menu (flows/stages/common actions)
- Right live output panel
- Dry-run toggle, kill running task, rerun last task
- Headless smoke test for CI/automation validation
"""

from __future__ import annotations

import argparse
import base64
import curses
import datetime as dt
import json
import os
import queue
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from handoff_prompt_utils import requirements_prompt_from_files

EXIT_OK = 0
EXIT_FAIL = 1

SUPPORTED_LOCALES = ("en", "zh")
PATH_FIELD_KEYS = {
    "spec_source",
    "handoff_root",
    "handoff_manifest",
    "source_requirements_root",
}
UI_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "locale.en": "English",
        "locale.zh": "Chinese",
        "title.python": "OpenChipFlow | Python frontend (stable) | lang={lang}",
        "hint.running": "Running: Ctrl+X requests stop, Ctrl+C x3 force quits",
        "hint.confirm": "Confirm armed: press Enter again to execute, Esc cancels",
        "hint.overlay": "Overlay open: Enter apply, Esc cancel, j/k navigate",
        "hint.palette": "Palette open: type filter text, supports mode:/tool:/advanced:",
        "hint.form": "Form open: Enter edit/apply, Tab complete path, j/k navigate, Esc cancel",
        "hint.ready": "Ready: / palette, Enter confirm, v switch log view, l language",
        "pane.commands": "NAVIGATION",
        "pane.palette": "PALETTE",
        "pane.output": "OUTPUT",
        "pane.form": "REQUEST FORM",
        "section.modes": "MODES",
        "section.tools": "TOOLS",
        "section.advanced": "ADVANCED",
        "panel.status": "STATUS",
        "panel.focus": "FOCUS",
        "panel.last": "LAST",
        "panel.outline": "OUTLINE",
        "panel.result": "RESULT",
        "panel.request": "REQUEST",
        "label.filter": "Filter",
        "label.desc": "Desc",
        "label.confirm": "Confirm",
        "label.preview": "Preview",
        "label.preview_only_result": "Preview only: commands were not executed.",
        "label.required": "required",
        "label.optional": "optional",
        "label.one_of": "one of two",
        "label.conditional": "conditional",
        "label.defaulted": "default",
        "label.none": "(none)",
        "label.view.logs": "LOGS",
        "label.view.out": "STDOUT",
        "label.view.err": "STDERR",
        "label.view.results": "RESULTS",
        "label.view.inputs": "INPUTS",
        "label.view.prompts": "PROMPTS",
        "label.view.basis": "BASIS",
        "label.view.requirements": "REQUIREMENTS",
        "label.view.review": "REVIEW",
        "label.view.feedback": "FEEDBACK",
        "label.request.mode": "Mode",
        "label.request.session": "Session",
        "label.request.run": "Run request",
        "label.request.cancel": "Cancel",
        "label.request.preview_requirements": "Preview Intake Contract",
        "label.request.copy_requirements": "Copy Intake Contract",
        "label.request.path": "Request path",
        "label.ui.path": "UI manifest",
        "label.artifacts": "Artifacts",
        "label.actions": "Next actions",
        "label.form.editing": "editing",
        "label.form.idle": "navigate",
        "request.spec_source": "Spec source path",
        "request.execution_mode": "Execution mode",
        "request.spec_import_mode": "Spec import mode",
        "request.handoff_root": "Handoff bundle root",
        "request.handoff_manifest": "Existing handoff manifest",
        "request.source_requirements_root": "Source requirements folder",
        "request.handoff_root_import": "Bundle import mode",
        "request.handoff_manifest_import": "Manifest import mode",
        "request.source_requirements_import": "Source requirements import",
        "request.target_state": "Expected delivery state",
        "request.semantic_review_mode": "Content review policy",
        "request.backend_policy": "Backend policy",
        "mode.spec_flow.title": "Spec Flow",
        "mode.spec_flow.desc": "Start from a spec input and choose plan or all in the form",
        "mode.handoff_intake.title": "Handoff Intake",
        "mode.handoff_intake.form_title": "Handoff Intake / Import & Review",
        "mode.handoff_intake.desc": "Audit raw handoff files and emit a gap report / repair prompt",
        "mode.incremental_verify_ready.title": "Verify-Ready Handoff",
        "mode.incremental_verify_ready.desc": "Run the verification loop from a verify-ready handoff manifest",
        "outline.spec_flow_depth": "Execution depth: plan | all",
        "advanced.direct_flow": "Direct Flow Run",
        "advanced.stage_quick_run": "Stage Quick Run",
        "advanced.rerun_failed_stage": "Rerun Failed Stage",
        "advanced.direct_flow.desc": "Run a backend flow directly without going through the mode form",
        "advanced.stage_quick_run.desc": "Run one backend stage directly for debugging",
        "advanced.rerun_failed_stage.desc": "Rerun the last failed backend stage",
        "mode.spec_flow.stage.precheck": "Precheck",
        "mode.spec_flow.stage.precheck.desc": "Check environment, tooling, and repo prerequisites before planning",
        "mode.spec_flow.stage.plan": "Plan",
        "mode.spec_flow.stage.plan.desc": "Normalize the spec and generate planning artifacts for review",
        "mode.spec_flow.stage.generate": "Generate RTL/TB",
        "mode.spec_flow.stage.generate.desc": "Run DE/DV generation and format the resulting sources",
        "mode.spec_flow.stage.prepare": "Prepare Verification",
        "mode.spec_flow.stage.prepare.desc": "Build schedule, validate tests, and materialize trace inputs",
        "mode.spec_flow.stage.smoke": "Smoke",
        "mode.spec_flow.stage.smoke.desc": "Execute the simulation smoke loop before full verification",
        "mode.spec_flow.stage.verify": "Verify",
        "mode.spec_flow.stage.verify.desc": "Produce the verification report from the generated bundle",
        "mode.spec_flow.stage.regress": "Regress",
        "mode.spec_flow.stage.regress.desc": "Run the broader regression after verify passes",
        "mode.spec_flow.stage.deliver": "Deliver",
        "mode.spec_flow.stage.deliver.desc": "Run final contract checks and publish deliverables",
        "mode.handoff_intake.stage.discover": "Discover Inputs",
        "mode.handoff_intake.stage.discover.desc": "Scan handoff files and identify candidate inputs",
        "mode.handoff_intake.stage.audit": "Audit Handoff",
        "mode.handoff_intake.stage.audit.desc": "Validate handoff structure, completeness, and consistency",
        "mode.handoff_intake.stage.feedback": "Emit Feedback",
        "mode.handoff_intake.stage.feedback.desc": "Emit the gap report, repair prompt, and candidate manifest",
        "mode.incremental_verify_ready.stage.validate": "Validate Handoff",
        "mode.incremental_verify_ready.stage.validate.desc": "Validate manifest/schema and build normalized handoff context",
        "mode.incremental_verify_ready.stage.prepare": "Prepare Verification",
        "mode.incremental_verify_ready.stage.prepare.desc": "Generate schedule and trace inputs from the verify-ready handoff",
        "mode.incremental_verify_ready.stage.quality": "Quality Gates",
        "mode.incremental_verify_ready.stage.quality.desc": "Run schema and gate checks before simulation",
        "mode.incremental_verify_ready.stage.smoke": "Smoke",
        "mode.incremental_verify_ready.stage.smoke.desc": "Run the incremental simulation smoke loop",
        "mode.incremental_verify_ready.stage.verify": "Verify",
        "mode.incremental_verify_ready.stage.verify.desc": "Generate the verification report",
        "mode.incremental_verify_ready.stage.regress": "Regress",
        "mode.incremental_verify_ready.stage.regress.desc": "Run regression for the incremental verification bundle",
        "mode.incremental_verify_ready.stage.compliance": "Compliance",
        "mode.incremental_verify_ready.stage.compliance.desc": "Check allowlist/compliance and final contract gates",
        "quick.keys": "Keys: / palette | Enter open/run | Shift+D dry-run | Shift+Up/Down scroll | v view | y copy active prompt | Ctrl+O/T/S overlays | l language | r/Shift+F rerun | Ctrl+C x3 quit",
        "label.handoff.source_requirements": "Source Requirements",
        "label.handoff.source_index": "Source Index",
        "label.handoff.review_status": "Review Status",
        "label.handoff.files": "Files",
        "label.handoff.path": "Path",
        "label.handoff.original": "Original",
        "label.handoff.unavailable_before_run": "Run Handoff Intake to populate this view.",
        "label.handoff.use_form_requirements": "Use the form actions to preview/copy the requirements prompt before running.",
        "overlay.help": "Help (?)",
        "overlay.model": "Model Select (Ctrl+O)",
        "overlay.flow": "Direct Flow Run",
        "overlay.stage": "Stage Quick Run (Ctrl+S)",
        "overlay.variant": "Variant (Ctrl+T)",
        "overlay.actions": "Enter to apply / Esc to cancel",
        "overlay.no_flow": "(no flow entries)",
        "overlay.no_stage": "(no stage entries)",
        "status.language": "Language switched to: {lang}",
        "status.select": "Select a command and press Enter to arm confirmation",
        "status.quit.idle": "Press Ctrl+C {remain} more time(s) to quit",
        "status.quit.running": "Press Ctrl+C {remain} more time(s) to force quit; current task will be stopped",
        "status.quit.esc_only": "Esc closes overlays/palette/confirm only; press Ctrl+C x3 to quit",
        "status.quit.q_only": "Press Ctrl+C x3 to quit",
        "status.path_base": "Path base: {base}",
        "status.path_complete.none": "No path match from: {base}",
        "status.path_complete.single": "Path completed",
        "status.path_complete.multi": "{count} matches: {sample}",
        "status.path_complete.disabled": "Path completion only works for path fields",
        "log.ready": "Ready. default: dry-run=OFF (Shift+D toggles)",
    },
    "zh": {
        "locale.en": "英文",
        "locale.zh": "中文",
        "title.python": "OpenChipFlow | Python 前端（稳定） | 语言={lang}",
        "hint.running": "运行中：Ctrl+X 请求停止，Ctrl+C 连按 3 次强制退出",
        "hint.confirm": "已进入确认态：再次按 Enter 执行，Esc 取消",
        "hint.overlay": "面板已打开：Enter 应用，Esc 取消，j/k 导航",
        "hint.palette": "命令面板已打开：可输入过滤文本，支持 mode:/tool:/advanced:",
        "hint.form": "表单已打开：Enter 编辑/应用，Tab 路径补全，j/k 导航，Esc 取消",
        "hint.ready": "就绪：/ 打开面板，Enter 确认，v 切日志视图，l 切语言",
        "pane.commands": "导航",
        "pane.palette": "命令面板",
        "pane.output": "输出",
        "pane.form": "请求表单",
        "section.modes": "模式",
        "section.tools": "工具",
        "section.advanced": "高级",
        "panel.status": "状态",
        "panel.focus": "焦点",
        "panel.last": "上次命令",
        "panel.outline": "流程大纲",
        "panel.result": "结果",
        "panel.request": "请求",
        "label.filter": "过滤",
        "label.desc": "说明",
        "label.confirm": "确认",
        "label.preview": "预览",
        "label.preview_only_result": "仅预演：本次没有真正执行命令。",
        "label.required": "必填",
        "label.optional": "可选",
        "label.one_of": "二选一",
        "label.conditional": "条件相关",
        "label.defaulted": "默认值",
        "label.none": "（无）",
        "label.view.logs": "日志",
        "label.view.out": "标准输出",
        "label.view.err": "标准错误",
        "label.view.results": "结果",
        "label.view.inputs": "输入",
        "label.view.prompts": "提示词",
        "label.view.basis": "依据",
        "label.view.requirements": "要求",
        "label.view.review": "审核",
        "label.view.feedback": "回喂",
        "label.request.mode": "模式",
        "label.request.session": "会话",
        "label.request.run": "执行请求",
        "label.request.cancel": "取消",
        "label.request.preview_requirements": "预览交接要求",
        "label.request.copy_requirements": "复制交接要求",
        "label.request.path": "请求文件",
        "label.ui.path": "UI Manifest",
        "label.artifacts": "产物",
        "label.actions": "下一步动作",
        "label.form.editing": "编辑中",
        "label.form.idle": "导航中",
        "request.spec_source": "Spec 文件路径",
        "request.execution_mode": "执行模式",
        "request.spec_import_mode": "Spec 导入方式",
        "request.handoff_root": "Handoff 交接包目录",
        "request.handoff_manifest": "已有 Handoff Manifest",
        "request.source_requirements_root": "原始需求目录",
        "request.handoff_root_import": "交接包导入方式",
        "request.handoff_manifest_import": "Manifest 导入方式",
        "request.source_requirements_import": "原始需求目录导入方式",
        "request.target_state": "期望交付状态",
        "request.semantic_review_mode": "内容审核策略",
        "request.backend_policy": "Backend 策略",
        "mode.spec_flow.title": "Spec Flow",
        "mode.spec_flow.desc": "从 spec 输入起步，并在表单中选择 plan 或 all",
        "mode.handoff_intake.title": "Handoff Intake",
        "mode.handoff_intake.form_title": "Handoff Intake / 导入与审核",
        "mode.handoff_intake.desc": "审计原始 handoff 文件，并输出 gap report / 补料提示",
        "mode.incremental_verify_ready.title": "Verify-Ready Handoff",
        "mode.incremental_verify_ready.desc": "从 verify-ready handoff manifest 直接进入验证闭环",
        "outline.spec_flow_depth": "执行深度：plan | all",
        "advanced.direct_flow": "直接运行 Flow",
        "advanced.stage_quick_run": "单独运行 Stage",
        "advanced.rerun_failed_stage": "重跑失败 Stage",
        "advanced.direct_flow.desc": "绕过模式表单，直接运行 backend flow",
        "advanced.stage_quick_run.desc": "直接运行单个 backend stage 用于调试",
        "advanced.rerun_failed_stage.desc": "重跑上一次失败的 backend stage",
        "mode.spec_flow.stage.precheck": "前置检查",
        "mode.spec_flow.stage.precheck.desc": "在规划前检查环境、工具链和仓库前提条件",
        "mode.spec_flow.stage.plan": "规划",
        "mode.spec_flow.stage.plan.desc": "规范化 spec 并生成可供人工检查的规划产物",
        "mode.spec_flow.stage.generate": "生成 RTL/TB",
        "mode.spec_flow.stage.generate.desc": "运行 DE/DV 生成并整理源文件输出",
        "mode.spec_flow.stage.prepare": "准备验证",
        "mode.spec_flow.stage.prepare.desc": "构建 schedule、校验测试并准备 trace 输入",
        "mode.spec_flow.stage.smoke": "冒烟",
        "mode.spec_flow.stage.smoke.desc": "在完整验证前执行仿真冒烟闭环",
        "mode.spec_flow.stage.verify": "验证",
        "mode.spec_flow.stage.verify.desc": "基于生成产物输出验证报告",
        "mode.spec_flow.stage.regress": "回归",
        "mode.spec_flow.stage.regress.desc": "在 verify 通过后执行更完整的回归",
        "mode.spec_flow.stage.deliver": "交付",
        "mode.spec_flow.stage.deliver.desc": "运行最终契约检查并产出交付物",
        "mode.handoff_intake.stage.discover": "发现输入",
        "mode.handoff_intake.stage.discover.desc": "扫描 handoff 文件并识别候选输入",
        "mode.handoff_intake.stage.audit": "审计 Handoff",
        "mode.handoff_intake.stage.audit.desc": "检查 handoff 的结构、完整性和一致性",
        "mode.handoff_intake.stage.feedback": "输出反馈",
        "mode.handoff_intake.stage.feedback.desc": "输出 gap report、补料提示和候选 manifest",
        "mode.incremental_verify_ready.stage.validate": "校验 Handoff",
        "mode.incremental_verify_ready.stage.validate.desc": "校验 manifest/schema 并构建规范化 handoff 上下文",
        "mode.incremental_verify_ready.stage.prepare": "准备验证",
        "mode.incremental_verify_ready.stage.prepare.desc": "从 verify-ready handoff 生成 schedule 和 trace 输入",
        "mode.incremental_verify_ready.stage.quality": "质量门禁",
        "mode.incremental_verify_ready.stage.quality.desc": "在仿真前运行 schema 和质量门禁检查",
        "mode.incremental_verify_ready.stage.smoke": "冒烟",
        "mode.incremental_verify_ready.stage.smoke.desc": "执行增量仿真冒烟闭环",
        "mode.incremental_verify_ready.stage.verify": "验证",
        "mode.incremental_verify_ready.stage.verify.desc": "生成验证报告",
        "mode.incremental_verify_ready.stage.regress": "回归",
        "mode.incremental_verify_ready.stage.regress.desc": "对增量验证产物执行回归",
        "mode.incremental_verify_ready.stage.compliance": "合规检查",
        "mode.incremental_verify_ready.stage.compliance.desc": "检查 allowlist / 合规门禁与最终契约门禁",
        "quick.keys": "快捷键：/ 命令面板 | Enter 打开/执行 | Shift+D 切 dry-run | Shift+上下滚日志 | v 切视图 | y 复制当前提示词 | Ctrl+O/T/S 面板 | l 切语言 | r/Shift+F 重跑 | Ctrl+C 连按 3 次退出",
        "label.handoff.source_requirements": "原始需求",
        "label.handoff.source_index": "来源索引",
        "label.handoff.review_status": "审核状态",
        "label.handoff.files": "文件",
        "label.handoff.path": "路径",
        "label.handoff.original": "原始路径",
        "label.handoff.unavailable_before_run": "请先运行 Handoff Intake 以生成该视图内容。",
        "label.handoff.use_form_requirements": "运行前请使用表单中的预览/复制按钮查看交接要求提示词。",
        "overlay.help": "帮助（?）",
        "overlay.model": "模型选择（Ctrl+O）",
        "overlay.flow": "直接运行 Flow",
        "overlay.stage": "阶段快跑（Ctrl+S）",
        "overlay.variant": "Variant 选择（Ctrl+T）",
        "overlay.actions": "Enter 应用 / Esc 取消",
        "overlay.no_flow": "（没有可用 flow）",
        "overlay.no_stage": "（没有可用 stage）",
        "status.language": "语言已切换为：{lang}",
        "status.select": "选择命令后按 Enter 进入确认态",
        "status.quit.idle": "再按 Ctrl+C {remain} 次退出",
        "status.quit.running": "再按 Ctrl+C {remain} 次强制退出；当前任务会被停止",
        "status.quit.esc_only": "Esc 只用于关闭面板/命令面板/确认态；退出请按 Ctrl+C 3 次",
        "status.quit.q_only": "退出请按 Ctrl+C 3 次",
        "status.path_base": "路径基准目录：{base}",
        "status.path_complete.none": "没有匹配路径，基准目录：{base}",
        "status.path_complete.single": "路径已补全",
        "status.path_complete.multi": "{count} 个匹配：{sample}",
        "status.path_complete.disabled": "只有路径字段支持补全",
        "log.ready": "就绪。默认：dry-run=OFF（Shift+D 切换）",
    },
}


@dataclass
class MenuItem:
    key: str
    kind: str
    title: str
    args: list[str]
    desc: str
    depth: int = 0
    selectable: bool = True
    parent_key: str = ""
    section: str = ""


@dataclass
class FormFieldSpec:
    key: str
    label_key: str
    kind: str  # text | choice | action
    required: bool = False
    status_key: str = ""
    choices: tuple[str, ...] = ()
    action: str = ""


@dataclass
class RequestFormState:
    mode: str
    title: str
    fields: list[FormFieldSpec]
    values: dict[str, str]
    selected: int = 0
    editing: bool = False
    buffer: str = ""
    message: str = ""


@dataclass
class OverlayItem:
    label: str
    value: str
    enabled: bool = True
    kind: str = "model"  # model | variant | flow | stage


@dataclass
class RuntimeState:
    model: str | None = None
    variant: str | None = None


class ProcessStreamer:
    def __init__(self, cmd: list[str], cwd: Path):
        self.cmd = cmd
        self.cwd = cwd
        self.proc: Optional[subprocess.Popen[str]] = None
        self.q: queue.Queue[tuple[str, str]] = queue.Queue()
        self.done = threading.Event()
        self.rc: Optional[int] = None

    def start(self) -> None:
        self.proc = subprocess.Popen(
            self.cmd,
            cwd=str(self.cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert self.proc.stdout is not None
        assert self.proc.stderr is not None

        def pump(pipe, tag: str):
            for line in iter(pipe.readline, ""):
                self.q.put((tag, line.rstrip("\n")))
            pipe.close()

        t1 = threading.Thread(target=pump, args=(self.proc.stdout, "OUT"), daemon=True)
        t2 = threading.Thread(target=pump, args=(self.proc.stderr, "ERR"), daemon=True)
        t1.start()
        t2.start()

        def waiter():
            self.rc = self.proc.wait()
            self.done.set()

        threading.Thread(target=waiter, daemon=True).start()

    def kill(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


def normalize_locale(value: str | None) -> str:
    raw = (value or "").strip().lower()
    return raw if raw in SUPPORTED_LOCALES else "en"


def toggle_locale(value: str) -> str:
    return "zh" if normalize_locale(value) == "en" else "en"


def tr(locale: str, key: str, **kwargs: Any) -> str:
    lang = normalize_locale(locale)
    text = UI_STRINGS.get(lang, UI_STRINGS["en"]).get(key) or UI_STRINGS["en"].get(key) or key
    return text.format(**kwargs)


def localized_text(value: Any, locale: str, fallback: str = "") -> str:
    if isinstance(value, dict):
        for key in (normalize_locale(locale), "en", "zh"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()
        return fallback
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def load_runner_config(project_root: Path, config_rel: str) -> dict[str, Any]:
    cfg_path = (project_root / config_rel).resolve()
    return json.loads(cfg_path.read_text(encoding="utf-8"))


def default_locale_from_config(cfg: dict[str, Any]) -> str:
    ui_cfg = cfg.get("ui") or {}
    return normalize_locale(ui_cfg.get("default_locale"))


def resolve_locale(cfg: dict[str, Any], cli_locale: str | None) -> str:
    return normalize_locale(cli_locale or os.getenv("CHIPFLOW_TUI_LANG") or default_locale_from_config(cfg))


def menu_texts(ui_entries: Any, key: str, locale: str, fallback_title: str, fallback_desc: str) -> tuple[str, str]:
    entry = ui_entries.get(key) if isinstance(ui_entries, dict) else {}
    if not isinstance(entry, dict):
        entry = {}
    title = localized_text(entry.get("title"), locale, fallback_title)
    desc = localized_text(entry.get("desc"), locale, fallback_desc)
    return title, desc


def request_mode_defs(locale: str) -> dict[str, dict[str, Any]]:
    return {
        "spec_flow": {
            "title": tr(locale, "mode.spec_flow.title"),
            "fields": [
                FormFieldSpec("spec_source", "request.spec_source", "text", required=True),
                FormFieldSpec("execution_mode", "request.execution_mode", "choice", required=True, choices=("plan", "all")),
                FormFieldSpec("spec_import_mode", "request.spec_import_mode", "choice", required=True, choices=("snapshot", "reference")),
                FormFieldSpec("submit", "label.request.run", "action", action="submit"),
                FormFieldSpec("cancel", "label.request.cancel", "action", action="cancel"),
            ],
            "defaults": {
                "spec_source": "",
                "execution_mode": "plan",
                "spec_import_mode": "snapshot",
            },
        },
        "handoff_intake": {
            "title": tr(locale, "mode.handoff_intake.form_title"),
            "fields": [
                FormFieldSpec("handoff_root", "request.handoff_root", "text", status_key="label.one_of"),
                FormFieldSpec("handoff_root_import", "request.handoff_root_import", "choice", status_key="label.defaulted", choices=("snapshot", "reference")),
                FormFieldSpec("handoff_manifest", "request.handoff_manifest", "text", status_key="label.one_of"),
                FormFieldSpec("handoff_manifest_import", "request.handoff_manifest_import", "choice", status_key="label.defaulted", choices=("reference", "snapshot")),
                FormFieldSpec("source_requirements_root", "request.source_requirements_root", "text", status_key="label.conditional"),
                FormFieldSpec("source_requirements_import", "request.source_requirements_import", "choice", status_key="label.defaulted", choices=("snapshot", "reference")),
                FormFieldSpec("target_state", "request.target_state", "choice", status_key="label.defaulted", choices=("", "analysis_only", "design_ready", "verify_ready")),
                FormFieldSpec("semantic_review_mode", "request.semantic_review_mode", "choice", status_key="label.defaulted", choices=("required", "auto", "off")),
                FormFieldSpec("preview_requirements", "label.request.preview_requirements", "action", action="preview_requirements"),
                FormFieldSpec("copy_requirements", "label.request.copy_requirements", "action", action="copy_requirements"),
                FormFieldSpec("submit", "label.request.run", "action", action="submit"),
                FormFieldSpec("cancel", "label.request.cancel", "action", action="cancel"),
            ],
            "defaults": {
                "handoff_root": "",
                "handoff_root_import": "snapshot",
                "handoff_manifest": "",
                "handoff_manifest_import": "reference",
                "source_requirements_root": "",
                "source_requirements_import": "snapshot",
                "target_state": "",
                "semantic_review_mode": "required",
            },
        },
        "incremental_verify_ready": {
            "title": tr(locale, "mode.incremental_verify_ready.title"),
            "fields": [
                FormFieldSpec("handoff_manifest", "request.handoff_manifest", "text", required=True),
                FormFieldSpec("handoff_manifest_import", "request.handoff_manifest_import", "choice", required=True, choices=("reference", "snapshot")),
                FormFieldSpec("backend_policy", "request.backend_policy", "text"),
                FormFieldSpec("submit", "label.request.run", "action", action="submit"),
                FormFieldSpec("cancel", "label.request.cancel", "action", action="cancel"),
            ],
            "defaults": {
                "handoff_manifest": "",
                "handoff_manifest_import": "reference",
                "backend_policy": "",
            },
        },
    }


def mode_stage_defs(locale: str) -> dict[str, list[tuple[str, str, str]]]:
    return {
        "spec_flow": [
            ("precheck", tr(locale, "mode.spec_flow.stage.precheck"), tr(locale, "mode.spec_flow.stage.precheck.desc")),
            ("plan", tr(locale, "mode.spec_flow.stage.plan"), tr(locale, "mode.spec_flow.stage.plan.desc")),
            ("generate", tr(locale, "mode.spec_flow.stage.generate"), tr(locale, "mode.spec_flow.stage.generate.desc")),
            ("prepare", tr(locale, "mode.spec_flow.stage.prepare"), tr(locale, "mode.spec_flow.stage.prepare.desc")),
            ("smoke", tr(locale, "mode.spec_flow.stage.smoke"), tr(locale, "mode.spec_flow.stage.smoke.desc")),
            ("verify", tr(locale, "mode.spec_flow.stage.verify"), tr(locale, "mode.spec_flow.stage.verify.desc")),
            ("regress", tr(locale, "mode.spec_flow.stage.regress"), tr(locale, "mode.spec_flow.stage.regress.desc")),
            ("deliver", tr(locale, "mode.spec_flow.stage.deliver"), tr(locale, "mode.spec_flow.stage.deliver.desc")),
        ],
        "handoff_intake": [
            ("discover", tr(locale, "mode.handoff_intake.stage.discover"), tr(locale, "mode.handoff_intake.stage.discover.desc")),
            ("audit", tr(locale, "mode.handoff_intake.stage.audit"), tr(locale, "mode.handoff_intake.stage.audit.desc")),
            ("feedback", tr(locale, "mode.handoff_intake.stage.feedback"), tr(locale, "mode.handoff_intake.stage.feedback.desc")),
        ],
        "incremental_verify_ready": [
            ("validate", tr(locale, "mode.incremental_verify_ready.stage.validate"), tr(locale, "mode.incremental_verify_ready.stage.validate.desc")),
            ("prepare", tr(locale, "mode.incremental_verify_ready.stage.prepare"), tr(locale, "mode.incremental_verify_ready.stage.prepare.desc")),
            ("quality", tr(locale, "mode.incremental_verify_ready.stage.quality"), tr(locale, "mode.incremental_verify_ready.stage.quality.desc")),
            ("smoke", tr(locale, "mode.incremental_verify_ready.stage.smoke"), tr(locale, "mode.incremental_verify_ready.stage.smoke.desc")),
            ("verify", tr(locale, "mode.incremental_verify_ready.stage.verify"), tr(locale, "mode.incremental_verify_ready.stage.verify.desc")),
            ("regress", tr(locale, "mode.incremental_verify_ready.stage.regress"), tr(locale, "mode.incremental_verify_ready.stage.regress.desc")),
            ("compliance", tr(locale, "mode.incremental_verify_ready.stage.compliance"), tr(locale, "mode.incremental_verify_ready.stage.compliance.desc")),
        ],
    }


def build_mode_items(locale: str) -> list[MenuItem]:
    items: list[MenuItem] = [
        MenuItem("section:modes", "section", tr(locale, "section.modes"), [], "", selectable=False, section="modes")
    ]
    mode_meta = {
        "spec_flow": (tr(locale, "mode.spec_flow.title"), tr(locale, "mode.spec_flow.desc")),
        "handoff_intake": (tr(locale, "mode.handoff_intake.title"), tr(locale, "mode.handoff_intake.desc")),
        "incremental_verify_ready": (
            tr(locale, "mode.incremental_verify_ready.title"),
            tr(locale, "mode.incremental_verify_ready.desc"),
        ),
    }
    for mode_key in ("spec_flow", "handoff_intake", "incremental_verify_ready"):
        title, desc = mode_meta[mode_key]
        items.append(MenuItem(mode_key, "mode", title, [], desc, section="modes"))
    return items


def build_tool_items(cfg: dict[str, Any], locale: str) -> list[MenuItem]:
    ui_cfg = cfg.get("ui") or {}
    command_ui = ui_cfg.get("commands") or {}
    items: list[MenuItem] = [
        MenuItem("section:tools", "section", tr(locale, "section.tools"), [], "", selectable=False, section="tools")
    ]
    for cmd_name, args, fallback_title, fallback_desc in (
        ("doctor", ["doctor"], "Environment Check", "Run precheck diagnostics only"),
        ("list", ["list"], "List Flows / Stages", "List configured flows and stages"),
    ):
        title, desc = menu_texts(command_ui, cmd_name, locale, fallback_title, fallback_desc)
        items.append(MenuItem(cmd_name, "tool", title, args, desc, section="tools"))
    return items


def build_advanced_items(locale: str) -> list[MenuItem]:
    return [
        MenuItem("section:advanced", "section", tr(locale, "section.advanced"), [], "", selectable=False, section="advanced"),
        MenuItem(
            "advanced.direct_flow",
            "advanced",
            tr(locale, "advanced.direct_flow"),
            ["direct_flow"],
            tr(locale, "advanced.direct_flow.desc"),
            section="advanced",
        ),
        MenuItem(
            "advanced.stage_quick_run",
            "advanced",
            tr(locale, "advanced.stage_quick_run"),
            ["stage_quick_run"],
            tr(locale, "advanced.stage_quick_run.desc"),
            section="advanced",
        ),
        MenuItem(
            "advanced.rerun_failed_stage",
            "advanced",
            tr(locale, "advanced.rerun_failed_stage"),
            ["rerun_failed_stage"],
            tr(locale, "advanced.rerun_failed_stage.desc"),
            section="advanced",
        ),
    ]


def build_flow_overlay_items(cfg: dict[str, Any], locale: str) -> list[OverlayItem]:
    ui_cfg = cfg.get("ui") or {}
    flow_ui = ui_cfg.get("flows") or {}
    items: list[OverlayItem] = []
    for flow_name in ("plan", "all", "handoff_intake", "incremental_verify_ready"):
        if flow_name not in (cfg.get("flows") or {}):
            continue
        title, _ = menu_texts(
            flow_ui,
            flow_name,
            locale,
            flow_name,
            flow_name,
        )
        items.append(OverlayItem(title, flow_name, True, "flow"))
    if not items:
        items.append(OverlayItem(tr(locale, "overlay.no_flow"), "", False, "flow"))
    return items


def build_stage_overlay_items(cfg: dict[str, Any], locale: str) -> list[OverlayItem]:
    ui_cfg = cfg.get("ui") or {}
    stage_ui = ui_cfg.get("stages") or {}
    items: list[OverlayItem] = []
    for stage_name, stage_cfg in (cfg.get("stages") or {}).items():
        title, _ = menu_texts(
            stage_ui,
            stage_name,
            locale,
            stage_name,
            str(stage_cfg.get("description", "")).strip(),
        )
        items.append(OverlayItem(title, stage_name, True, "stage"))
    if not items:
        items.append(OverlayItem(tr(locale, "overlay.no_stage"), "", False, "stage"))
    return items


def build_menu_items(cfg: dict[str, Any], locale: str) -> list[MenuItem]:
    items: list[MenuItem] = []
    items.extend(build_mode_items(locale))
    items.extend(build_tool_items(cfg, locale))
    items.extend(build_advanced_items(locale))
    return items


def mode_outline_lines(locale: str, mode_key: str) -> list[str]:
    stage_meta = mode_stage_defs(locale).get(mode_key) or []
    if not stage_meta:
        return []
    lines: list[str] = []
    if mode_key == "spec_flow":
        lines.append(tr(locale, "outline.spec_flow_depth"))
    for _, stage_title, _ in stage_meta:
        lines.append(f"  - {stage_title}")
    return lines


def first_selectable_index(items: list[MenuItem]) -> int:
    for idx, item in enumerate(items):
        if item.selectable:
            return idx
    return 0


def next_selectable_index(items: list[MenuItem], current: int, step: int) -> int:
    if not items or not any(item.selectable for item in items):
        return 0
    idx = current
    for _ in range(len(items)):
        idx = (idx + step) % len(items)
        if items[idx].selectable:
            return idx
    return current


def restore_selection(items: list[MenuItem], previous: MenuItem | None) -> int:
    if not items:
        return 0
    if previous is None:
        return first_selectable_index(items)
    for idx, cand in enumerate(items):
        if cand.selectable and cand.kind == previous.kind and cand.key == previous.key:
            return idx
    return first_selectable_index(items)


def load_items(project_root: Path, config_rel: str, locale: str | None = None) -> list[MenuItem]:
    cfg = load_runner_config(project_root, config_rel)
    active_locale = resolve_locale(cfg, locale)
    return build_menu_items(cfg, active_locale)


def load_capabilities(project_root: Path) -> dict[str, Any]:
    cap_path = project_root / "artifacts/capabilities/capabilities.json"
    if not cap_path.exists():
        return {}
    try:
        return json.loads(cap_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def model_profiles(caps: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not isinstance(caps, dict):
        return {}
    catalog = caps.get("runtime_catalog") or {}
    profiles = catalog.get("model_profiles") or {}
    return profiles if isinstance(profiles, dict) else {}


def model_profile(caps: dict[str, Any], model: str | None) -> dict[str, Any] | None:
    if not model:
        return None
    return model_profiles(caps).get(model)


def model_family(caps: dict[str, Any], model: str | None) -> str:
    profile = model_profile(caps, model)
    if not isinstance(profile, dict):
        return ""
    return str(profile.get("family") or "").strip()


def default_variant_for_model(caps: dict[str, Any], model: str | None) -> str | None:
    profile = model_profile(caps, model)
    if not isinstance(profile, dict):
        return None
    val = profile.get("default_variant")
    return str(val).strip() if val else None


def display_variant_label(caps: dict[str, Any], model: str | None, variant: str | None) -> str:
    profile = model_profile(caps, model)
    if isinstance(profile, dict):
        variants = profile.get("variants") or []
        if not variants:
            return "n/a"
        target = variant or default_variant_for_model(caps, model) or ""
        for item in variants:
            if not isinstance(item, dict):
                continue
            value = str(item.get("value") or "").strip()
            if value == target:
                return str(item.get("label") or value).strip() or value
    return variant or "default"


def variant_status_text(caps: dict[str, Any], runtime: RuntimeState) -> str:
    profile = model_profile(caps, runtime.model)
    if isinstance(profile, dict):
        variants = profile.get("variants") or []
        if not variants:
            return "n/a"
        return display_variant_label(caps, runtime.model, runtime.variant)
    return runtime.variant or "default"


def model_overlay_label(caps: dict[str, Any], model: str) -> str:
    profile = model_profile(caps, model) or {}
    family = str(profile.get("family") or "").strip()
    label = str(profile.get("label") or model).strip() or model
    return f"{family}: {label}" if family else label


def build_model_overlay_items(caps: dict[str, Any]) -> list[OverlayItem]:
    items: list[OverlayItem] = [OverlayItem("<default>", "", True, "model")]

    catalog = ((caps.get("runtime_catalog") or {}).get("models") or []) if isinstance(caps, dict) else []
    tools = (caps.get("tools") or {}) if isinstance(caps, dict) else {}

    seen: set[str] = set()
    ordered_models: list[str] = []
    for m in catalog:
        if isinstance(m, str) and m.strip():
            key = m.strip()
            if key not in seen:
                seen.add(key)
                ordered_models.append(key)

    extra_models: set[str] = set()
    for tool in tools.values() if isinstance(tools, dict) else []:
        choices = (tool.get("choices") or {}).get("model") or []
        for m in choices:
            if isinstance(m, str) and m.strip():
                extra_models.add(m.strip())

    for m in sorted(extra_models):
        if m not in seen:
            ordered_models.append(m)

    for m in ordered_models:
        items.append(OverlayItem(model_overlay_label(caps, m), m, True, "model"))

    if len(items) == 1:
        items.append(OverlayItem("(no selectable models from capability probe)", "", False, "model"))
    return items


def build_variant_overlay_items(caps: dict[str, Any], selected_model: str | None) -> list[OverlayItem]:
    if not selected_model:
        return [OverlayItem("(select model first)", "", False, "variant")]

    profile = model_profile(caps, selected_model)
    if not isinstance(profile, dict):
        return [OverlayItem("(no variant profile for selected model)", "", False, "variant")]

    variants = profile.get("variants") or []
    if not variants:
        return [OverlayItem("(selected model has no separate variant)", "", False, "variant")]

    default_variant = display_variant_label(caps, selected_model, None)
    items: list[OverlayItem] = [OverlayItem(f"variant: <default={default_variant}>", "", True, "variant")]
    for item in variants:
        if not isinstance(item, dict):
            continue
        value = str(item.get("value") or "").strip()
        label = str(item.get("label") or value).strip()
        if not value:
            continue
        items.append(OverlayItem(f"variant: {label}", value, True, "variant"))
    return items


def build_runner_cmd(runner: list[str], item_args: list[str], dry_run: bool, runtime: RuntimeState) -> list[str]:
    cmd = runner + item_args + (["--dry-run"] if dry_run else [])
    if runtime.model:
        cmd += ["--model", runtime.model]
    if runtime.variant:
        cmd += ["--variant", runtime.variant]
    return cmd


def build_request_form(cfg: dict[str, Any], locale: str, mode: str) -> RequestFormState:
    defs = request_mode_defs(locale)
    spec = defs[mode]
    return RequestFormState(
        mode=mode,
        title=spec["title"],
        fields=spec["fields"],
        values=dict(spec["defaults"]),
        message="",
    )


def cycle_choice(choices: tuple[str, ...], current: str, step: int = 1) -> str:
    if not choices:
        return current
    try:
        idx = choices.index(current)
    except ValueError:
        idx = 0
    return choices[(idx + step) % len(choices)]


def validate_request_form(form: RequestFormState) -> str | None:
    values = form.values
    if form.mode == "spec_flow":
        if not values.get("spec_source", "").strip():
            return "spec_source is required"
        return None
    if form.mode == "handoff_intake":
        if not values.get("handoff_root", "").strip() and not values.get("handoff_manifest", "").strip():
            return "handoff_root or handoff_manifest is required"
        return None
    if form.mode == "incremental_verify_ready":
        if not values.get("handoff_manifest", "").strip():
            return "handoff_manifest is required"
        return None
    return "unsupported request mode"


def is_path_field(field: FormFieldSpec) -> bool:
    return field.kind == "text" and field.key in PATH_FIELD_KEYS


def display_input_path(target: Path, project_root: Path, original: str) -> str:
    raw = original.strip()
    if raw.startswith("~"):
        home = Path.home().resolve()
        try:
            rel = target.relative_to(home)
            return "~" if str(rel) == "." else f"~/{rel.as_posix()}"
        except ValueError:
            return str(target)
    expanded = Path(os.path.expanduser(raw))
    if expanded.is_absolute():
        return str(target)
    try:
        return str(target.relative_to(project_root))
    except ValueError:
        return str(target)


def path_completion_base(project_root: Path, raw: str) -> tuple[Path, str]:
    text = raw.strip()
    if not text:
        return project_root.resolve(), ""

    expanded = os.path.expanduser(text)
    candidate = Path(expanded)
    if text.endswith(os.sep):
        base_dir = candidate if candidate.is_absolute() else (project_root / candidate)
        return base_dir.resolve(), ""

    if candidate.is_absolute():
        return candidate.parent.resolve(), candidate.name

    base_dir = (project_root / candidate.parent).resolve()
    return base_dir, candidate.name


def complete_path_input(project_root: Path, raw: str, locale: str, *, limit: int = 5) -> tuple[str | None, str]:
    base_dir, prefix = path_completion_base(project_root, raw)
    if not base_dir.exists() or not base_dir.is_dir():
        return None, tr(locale, "status.path_complete.none", base=str(base_dir))

    try:
        entries = sorted(base_dir.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
    except OSError:
        return None, tr(locale, "status.path_complete.none", base=str(base_dir))

    matches = [entry for entry in entries if entry.name.startswith(prefix)]
    if not matches:
        return None, tr(locale, "status.path_complete.none", base=str(base_dir))

    if len(matches) == 1:
        target = matches[0]
        text = display_input_path(target, project_root, raw)
        if target.is_dir():
            text = text.rstrip("/") + "/"
        return text, tr(locale, "status.path_complete.single")

    common = os.path.commonprefix([entry.name for entry in matches])
    if common and common != prefix:
        target = base_dir / common
        return display_input_path(target, project_root, raw), tr(locale, "status.path_complete.multi", count=len(matches), sample=", ".join(entry.name for entry in matches[:limit]))

    sample = ", ".join(entry.name + ("/" if entry.is_dir() else "") for entry in matches[:limit])
    return None, tr(locale, "status.path_complete.multi", count=len(matches), sample=sample)


def request_manifest_dir(project_root: Path, session_id: str) -> Path:
    return (project_root / "artifacts" / "requests" / session_id).resolve()


def create_request_manifest_payload(
    form: RequestFormState,
    *,
    session_id: str,
    dry_run: bool,
    runtime: RuntimeState,
) -> dict[str, Any]:
    values = form.values
    payload: dict[str, Any] = {
        "schema_version": "runner_request_manifest/v1",
        "session_id": session_id,
        "mode": form.mode,
        "execution": {
            "dry_run": dry_run,
        },
        "runtime": {},
        "inputs": {},
    }
    if runtime.model:
        payload["runtime"]["model"] = runtime.model
    if runtime.variant:
        payload["runtime"]["variant"] = runtime.variant

    if form.mode == "spec_flow":
        payload["execution"]["mode"] = values.get("execution_mode", "plan")
        payload["inputs"]["spec_source"] = {
            "path": values.get("spec_source", "").strip(),
            "import_mode": values.get("spec_import_mode", "snapshot"),
            "kind": "file",
        }
    elif form.mode == "handoff_intake":
        root = values.get("handoff_root", "").strip()
        manifest = values.get("handoff_manifest", "").strip()
        source_requirements_root = values.get("source_requirements_root", "").strip()
        if root:
            payload["inputs"]["handoff_root"] = {
                "path": root,
                "import_mode": values.get("handoff_root_import", "snapshot"),
                "kind": "directory",
            }
        if manifest:
            payload["inputs"]["handoff_manifest"] = {
                "path": manifest,
                "import_mode": values.get("handoff_manifest_import", "reference"),
                "kind": "file",
            }
        if source_requirements_root:
            payload["inputs"]["source_requirements_root"] = {
                "path": source_requirements_root,
                "import_mode": values.get("source_requirements_import", "snapshot"),
                "kind": "directory",
            }
        target_state = values.get("target_state", "").strip()
        if target_state:
            payload["inputs"]["target_state"] = target_state
        semantic_review_mode = values.get("semantic_review_mode", "").strip()
        if semantic_review_mode:
            payload["inputs"]["semantic_review_mode"] = semantic_review_mode
    elif form.mode == "incremental_verify_ready":
        payload["inputs"]["handoff_manifest"] = {
            "path": values.get("handoff_manifest", "").strip(),
            "import_mode": values.get("handoff_manifest_import", "reference"),
            "kind": "file",
        }
        backend_policy = values.get("backend_policy", "").strip()
        if backend_policy:
            payload["inputs"]["backend_policy"] = backend_policy
    return payload


def write_request_manifest(project_root: Path, payload: dict[str, Any]) -> Path:
    session_id = str(payload.get("session_id") or "").strip() or dt.datetime.now().strftime("session_%Y%m%d_%H%M%S_%f")
    out_dir = request_manifest_dir(project_root, session_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "request.form.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


def build_request_cmd(runner: list[str], manifest_path: Path, runtime: RuntimeState) -> list[str]:
    cmd = runner + ["request", "--request-manifest", str(manifest_path)]
    if runtime.model:
        cmd += ["--model", runtime.model]
    if runtime.variant:
        cmd += ["--variant", runtime.variant]
    return cmd


MANIFEST_LINE_RE = re.compile(r"^\[MANIFEST\]\s+(.+)$")


def parse_manifest_path(text: str) -> Path | None:
    match = MANIFEST_LINE_RE.match(text.strip())
    if not match:
        return None
    return Path(match.group(1).strip()).expanduser()


def load_ui_manifest(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _extract_session_id_from_path(project_root: Path, raw_path: str) -> str | None:
    raw = raw_path.strip()
    if not raw:
        return None
    candidate = Path(os.path.expanduser(raw))
    target = candidate.resolve() if candidate.is_absolute() else (project_root / candidate).resolve()
    try:
        rel = target.relative_to(project_root.resolve())
    except ValueError:
        return None
    parts = rel.parts
    for idx in range(len(parts) - 2):
        if parts[idx : idx + 2] == ("cocotb_ex", "artifacts") and idx + 3 < len(parts) and parts[idx + 2] == "sessions":
            return parts[idx + 3]
        if parts[idx : idx + 2] == ("artifacts", "sessions") and idx + 2 < len(parts):
            return parts[idx + 2]
    return None


def session_id_hint_for_form(project_root: Path, form: RequestFormState) -> str | None:
    if form.mode == "incremental_verify_ready":
        return _extract_session_id_from_path(project_root, form.values.get("handoff_manifest", ""))
    if form.mode == "handoff_intake":
        for key in ("handoff_manifest", "handoff_root"):
            hinted = _extract_session_id_from_path(project_root, form.values.get(key, ""))
            if hinted:
                return hinted
    return None


def requirements_prompt_text(target_state: str) -> str:
    state = target_state.strip() or "verify_ready"
    return requirements_prompt_from_files(target_state=state)


def _prompt_entries_from_manifest(manifest: dict[str, Any] | None) -> list[dict[str, str]]:
    if not manifest:
        return []
    artifacts = {
        str(item.get("id") or ""): item
        for item in (manifest.get("primary_artifacts") or [])
        if isinstance(item, dict)
    }
    entries: list[dict[str, str]] = []
    for artifact_id, label in (
        ("handoff_requirements_prompt", "handoff_requirements_prompt.txt"),
        ("handoff_contract_repair_prompt", "handoff_contract_repair_prompt.txt"),
        ("handoff_semantic_repair_prompt", "handoff_semantic_repair_prompt.txt"),
        ("handoff_repair_prompt", "handoff_repair_prompt.txt"),
    ):
        item = artifacts.get(artifact_id)
        if not item or not item.get("exists"):
            continue
        abs_path = str(item.get("abs_path") or "")
        if not abs_path:
            continue
        try:
            content = Path(abs_path).read_text(encoding="utf-8")
        except Exception:
            continue
        entries.append({"id": artifact_id, "label": label, "path": abs_path, "content": content})
    return entries


def _artifact_map_from_manifest(manifest: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not manifest:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for item in manifest.get("primary_artifacts") or []:
        if not isinstance(item, dict):
            continue
        artifact_id = str(item.get("id") or "").strip()
        if artifact_id:
            out[artifact_id] = item
    return out


def _input_artifact_by_name(manifest: dict[str, Any] | None, name: str) -> dict[str, Any] | None:
    if not manifest:
        return None
    for item in manifest.get("input_artifacts") or []:
        if isinstance(item, dict) and str(item.get("name") or "").strip() == name:
            return item
    return None


def _read_text_if_exists(path_value: str) -> str:
    path = str(path_value or "").strip()
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8")
    except Exception:
        return ""


def _read_json_if_exists(path_value: str) -> dict[str, Any] | None:
    raw = _read_text_if_exists(path_value)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _list_reference_files(path_value: str) -> list[str]:
    root = Path(str(path_value or "").strip())
    if not root.exists() or not root.is_dir():
        return []
    files: list[str] = []
    for child in sorted(root.rglob("*")):
        if not child.is_file():
            continue
        try:
            files.append(str(child.relative_to(root)))
        except Exception:
            files.append(str(child))
        if len(files) >= 32:
            break
    return files


def _form_or_input_value(form_state: RequestFormState | None, manifest: dict[str, Any] | None, key: str) -> tuple[str, str]:
    if manifest:
        item = _input_artifact_by_name(manifest, key)
        if item:
            return (
                str(item.get("resolved_path") or item.get("abs_path") or item.get("path") or "").strip(),
                str(item.get("original_path") or "").strip(),
            )
    if form_state and form_state.mode == "handoff_intake":
        return form_state.values.get(key, "").strip(), ""
    return "", ""


def active_result_mode(
    result_manifest: dict[str, Any] | None,
    form_state: RequestFormState | None = None,
    current_item: MenuItem | None = None,
) -> str:
    if form_state is not None and form_state.mode:
        return form_state.mode
    if result_manifest:
        mode = str(result_manifest.get("mode") or "").strip()
        if mode:
            return mode
    if current_item is not None and current_item.kind == "mode":
        return current_item.key
    return ""


def available_result_views(active_mode: str) -> list[str]:
    if active_mode == "handoff_intake":
        return ["ALL", "OUT", "ERR", "BASIS", "REQUIREMENTS", "REVIEW", "FEEDBACK"]
    return ["ALL", "OUT", "ERR", "RESULTS", "INPUTS", "PROMPTS"]


def build_prompt_lines(
    locale: str,
    manifest: dict[str, Any] | None,
    manual_prompts: list[dict[str, str]] | None = None,
) -> list[str]:
    entries = manual_prompts if manual_prompts else _prompt_entries_from_manifest(manifest)
    if not entries:
        return [tr(locale, "label.none")]
    lines: list[str] = []
    for idx, entry in enumerate(entries):
        if idx:
            lines.extend(["", "---", ""])
        lines.append(f"{entry['label']}:")
        path = entry.get("path", "").strip()
        if path:
            lines.append(f"path: {path}")
        lines.append("")
        lines.extend((entry.get("content") or "").splitlines())
    return lines


def select_prompt_entry(
    manifest: dict[str, Any] | None,
    manual_prompts: list[dict[str, str]] | None = None,
    preferred_ids: tuple[str, ...] = (),
) -> dict[str, str] | None:
    entries = manual_prompts if manual_prompts else _prompt_entries_from_manifest(manifest)
    if not entries:
        return None
    if preferred_ids:
        for wanted in preferred_ids:
            for entry in entries:
                if entry.get("id") == wanted:
                    return entry
    return entries[0]


def copy_text_to_clipboard(project_root: Path, text: str, label: str) -> str:
    payload = text if text.endswith("\n") else text + "\n"
    osc52 = f"\033]52;c;{base64.b64encode(payload.encode('utf-8')).decode('ascii')}\a"
    try:
        with open("/dev/tty", "w", encoding="utf-8") as tty:
            tty.write(osc52)
            tty.flush()
        return f"Copied {label} via OSC52"
    except Exception:
        pass

    commands = []
    if shutil.which("wl-copy"):
        commands.append(["wl-copy"])
    if shutil.which("xclip"):
        commands.append(["xclip", "-selection", "clipboard"])
    if shutil.which("xsel"):
        commands.append(["xsel", "--clipboard", "--input"])
    if shutil.which("pbcopy"):
        commands.append(["pbcopy"])
    if shutil.which("clip.exe"):
        commands.append(["clip.exe"])
    for cmd in commands:
        try:
            subprocess.run(cmd, input=payload, text=True, check=True, capture_output=True)
            return f"Copied {label} via {Path(cmd[0]).name}"
        except Exception:
            continue

    out_dir = (project_root / "artifacts" / "clipboard").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = Path(tempfile.mkstemp(prefix="prompt_", suffix=".txt", dir=out_dir)[1])
    out_file.write_text(payload, encoding="utf-8")
    return f"Clipboard unavailable; wrote {label} to {out_file}"


def preferred_prompt_to_copy(
    manifest: dict[str, Any] | None,
    manual_prompts: list[dict[str, str]] | None = None,
) -> dict[str, str] | None:
    return select_prompt_entry(manifest, manual_prompts, (
        "handoff_semantic_repair_prompt",
        "handoff_contract_repair_prompt",
        "handoff_repair_prompt",
        "handoff_requirements_prompt",
    ))


def build_handoff_basis_lines(
    locale: str,
    manifest: dict[str, Any] | None,
    form_state: RequestFormState | None = None,
) -> list[str]:
    lines: list[str] = []
    if manifest:
        lines.append(f"{tr(locale, 'label.view.basis')}: mode={manifest.get('mode')}")
        req_path = manifest.get("request_manifest") or tr(locale, "label.none")
        lines.append(f"{tr(locale, 'label.request.path')}: {req_path}")
    else:
        lines.append(f"{tr(locale, 'label.view.basis')}: mode=handoff_intake")
    handoff_root, handoff_root_original = _form_or_input_value(form_state, manifest, "handoff_root")
    handoff_manifest, handoff_manifest_original = _form_or_input_value(form_state, manifest, "handoff_manifest")
    source_root, source_root_original = _form_or_input_value(form_state, manifest, "source_requirements_root")

    lines.append("---")
    lines.append("Handoff")
    lines.append(f"- handoff_root: {handoff_root or tr(locale, 'label.none')}")
    if handoff_root_original:
        lines.append(f"  {tr(locale, 'label.handoff.original')}: {handoff_root_original}")
    lines.append(f"- handoff_manifest: {handoff_manifest or tr(locale, 'label.none')}")
    if handoff_manifest_original:
        lines.append(f"  {tr(locale, 'label.handoff.original')}: {handoff_manifest_original}")

    lines.append("---")
    lines.append(tr(locale, "label.handoff.source_requirements"))
    lines.append(f"{tr(locale, 'label.handoff.path')}: {source_root or tr(locale, 'label.none')}")
    if source_root_original:
        lines.append(f"{tr(locale, 'label.handoff.original')}: {source_root_original}")
    ref_files = _list_reference_files(source_root)
    if ref_files:
        lines.append(f"{tr(locale, 'label.handoff.files')}:")
        lines.extend(f"- {item}" for item in ref_files)

    source_index_item = _artifact_map_from_manifest(manifest).get("handoff_source_index")
    if source_index_item and source_index_item.get("exists"):
        source_index_path = str(source_index_item.get("abs_path") or "").strip()
        source_index = _read_json_if_exists(source_index_path) or {}
        lines.append("---")
        lines.append(tr(locale, "label.handoff.source_index"))
        lines.append(f"{tr(locale, 'label.handoff.path')}: {source_index_path or tr(locale, 'label.none')}")
        if source_index:
            lines.append(f"- semantic_review_mode: {source_index.get('semantic_review_mode', tr(locale, 'label.none'))}")
            lines.append(f"- available: {source_index.get('available', tr(locale, 'label.none'))}")
            ref_docs = source_index.get("reference_docs") or []
            if isinstance(ref_docs, list):
                lines.append(f"- reference_docs: {len(ref_docs)}")

    if len(lines) == 1 and not manifest:
        lines.append(tr(locale, "label.handoff.unavailable_before_run"))
    return lines


def build_handoff_requirements_lines(
    locale: str,
    manifest: dict[str, Any] | None,
    manual_prompts: list[dict[str, str]] | None = None,
    form_state: RequestFormState | None = None,
) -> list[str]:
    entry = select_prompt_entry(manifest, manual_prompts, ("handoff_requirements_prompt",))
    if entry is None:
        if form_state is not None and form_state.mode == "handoff_intake":
            return [tr(locale, "label.handoff.use_form_requirements")]
        return [tr(locale, "label.none")]
    return build_prompt_lines(locale, manifest, [entry])


def build_handoff_review_lines(locale: str, manifest: dict[str, Any] | None) -> list[str]:
    if not manifest:
        return [tr(locale, "label.handoff.unavailable_before_run")]
    artifacts = _artifact_map_from_manifest(manifest)
    contract_item = artifacts.get("handoff_contract_audit")
    semantic_item = artifacts.get("handoff_semantic_review")
    acceptance_item = artifacts.get("handoff_acceptance")
    contract = _read_json_if_exists(str(contract_item.get("abs_path") or "")) if contract_item else None
    semantic = _read_json_if_exists(str(semantic_item.get("abs_path") or "")) if semantic_item else None
    acceptance = _read_json_if_exists(str(acceptance_item.get("abs_path") or "")) if acceptance_item else None

    lines: list[str] = [tr(locale, "label.handoff.review_status")]
    lines.append(f"- contract: {(contract or {}).get('status', tr(locale, 'label.none'))}")
    lines.append(f"- semantic: {(acceptance or {}).get('semantic_status', (semantic or {}).get('status', tr(locale, 'label.none')))}")
    lines.append(f"- acceptance: {(acceptance or {}).get('status', tr(locale, 'label.none'))}")

    if contract_item:
        lines.extend(["---", "Contract audit", f"{tr(locale, 'label.handoff.path')}: {contract_item.get('abs_path') or contract_item.get('path') or ''}"])
        if contract:
            lines.append(f"- target_state: {contract.get('target_state', tr(locale, 'label.none'))}")
            lines.append(f"- inferred_state: {contract.get('inferred_state', tr(locale, 'label.none'))}")
            lines.append(f"- semantic_review_mode: {contract.get('semantic_review_mode', tr(locale, 'label.none'))}")
            lines.append(f"- semantic_review_requested: {contract.get('semantic_review_requested', tr(locale, 'label.none'))}")

    if semantic_item:
        lines.extend(["---", "Semantic review", f"{tr(locale, 'label.handoff.path')}: {semantic_item.get('abs_path') or semantic_item.get('path') or ''}"])
        if semantic:
            summary = str(semantic.get("summary") or "").strip()
            if summary:
                lines.append(summary)
            findings = semantic.get("findings") or []
            if isinstance(findings, list) and findings:
                lines.append("")
                for finding in findings:
                    if not isinstance(finding, dict):
                        continue
                    severity = finding.get("severity", "?")
                    code = finding.get("code", "?")
                    message = finding.get("message", "")
                    lines.append(f"- [{severity}] {code}: {message}")

    if acceptance_item:
        lines.extend(["---", "Acceptance", f"{tr(locale, 'label.handoff.path')}: {acceptance_item.get('abs_path') or acceptance_item.get('path') or ''}"])
        if acceptance:
            reason = str(acceptance.get("semantic_reason") or "").strip()
            if reason:
                lines.append(f"- reason: {reason}")
    return lines


def build_handoff_feedback_lines(
    locale: str,
    manifest: dict[str, Any] | None,
    manual_prompts: list[dict[str, str]] | None = None,
) -> list[str]:
    entries = manual_prompts if manual_prompts else _prompt_entries_from_manifest(manifest)
    feedback_entries = [
        entry
        for entry in entries
        if entry.get("id") in {"handoff_contract_repair_prompt", "handoff_semantic_repair_prompt", "handoff_repair_prompt"}
    ]
    if not feedback_entries:
        return [tr(locale, "label.none")]
    return build_prompt_lines(locale, manifest, feedback_entries)


def result_view_label(locale: str, log_view: str, active_mode: str = "") -> str:
    mapping = {
        "ALL": "label.view.logs",
        "OUT": "label.view.out",
        "ERR": "label.view.err",
        "RESULTS": "label.view.results",
        "INPUTS": "label.view.inputs",
        "PROMPTS": "label.view.prompts",
        "BASIS": "label.view.basis",
        "REQUIREMENTS": "label.view.requirements",
        "REVIEW": "label.view.review",
        "FEEDBACK": "label.view.feedback",
    }
    return tr(locale, mapping.get(log_view, "label.view.logs"))


def build_visible_log_lines(
    locale: str,
    logs: list[str],
    log_view: str,
    result_manifest: dict[str, Any] | None,
    manual_prompts: list[dict[str, str]] | None = None,
    active_mode: str = "",
    form_state: RequestFormState | None = None,
) -> list[str]:
    if log_view == "OUT":
        return [ln for ln in logs if ln.startswith("[O]") or ln.startswith("[SYS]")]
    if log_view == "ERR":
        return [ln for ln in logs if ln.startswith("[E]") or ln.startswith("[SYS]")]
    if log_view in {"RESULTS", "INPUTS", "PROMPTS", "BASIS", "REQUIREMENTS", "REVIEW", "FEEDBACK"}:
        return build_result_lines(locale, result_manifest, log_view, manual_prompts=manual_prompts, active_mode=active_mode, form_state=form_state)
    return list(logs)


def slice_visible_log_lines(visible_logs: list[str], max_lines: int, scroll_offset: int) -> tuple[list[str], int, int]:
    if max_lines <= 0:
        return [], 0, 0
    total = len(visible_logs)
    max_scroll = max(0, total - max_lines)
    effective_scroll = min(max(0, scroll_offset), max_scroll)
    end = max(0, total - effective_scroll)
    start = max(0, end - max_lines)
    return visible_logs[start:end], effective_scroll, max_scroll


def char_display_width(ch: str) -> int:
    if not ch:
        return 0
    if ch == "\t":
        return 4
    if unicodedata.combining(ch):
        return 0
    if unicodedata.east_asian_width(ch) in {"F", "W"}:
        return 2
    return 1


def wrap_display_text(text: str, max_width: int) -> list[str]:
    if max_width <= 0:
        return []
    normalized = (text or "").replace("\t", "    ")
    blocks = normalized.splitlines() or [""]
    lines: list[str] = []
    for block in blocks:
        if block == "":
            lines.append("")
            continue
        current: list[str] = []
        current_width = 0
        for ch in block:
            ch_width = max(1, char_display_width(ch))
            if current and current_width + ch_width > max_width:
                lines.append("".join(current))
                current = [ch]
                current_width = ch_width
                continue
            current.append(ch)
            current_width += ch_width
        if current:
            lines.append("".join(current))
    return lines or [""]


def wrap_panel_lines(lines: list[str], max_width: int) -> list[str]:
    wrapped: list[str] = []
    for line in lines:
        wrapped.extend(wrap_display_text(str(line), max_width))
    return wrapped


def help_overlay_lines(locale: str) -> list[str]:
    if normalize_locale(locale) == "zh":
        return [
            "按 ? 或 Esc 关闭",
            "",
            "/ 命令面板 | Enter 打开/执行 | v 切视图 | l 切语言",
            "Ctrl+O 模型 | Ctrl+T variant | Ctrl+S stage",
            "r 重跑上次 | Shift+F 重跑失败 stage",
            "Shift+D 切换 dry-run",
            "Shift+上下滚动输出",
            "Ctrl+X 停止 | Ctrl+C 连按 3 次强退",
        ]
    return [
        "Press ? or Esc to close",
        "",
        "/ palette | Enter open/run | v view | l language",
        "Ctrl+O model | Ctrl+T variant | Ctrl+S stage",
        "r rerun last | Shift+F rerun failed stage",
        "Shift+D dry-run toggle",
        "Shift+Up/Down scroll output",
        "Ctrl+X stop | Ctrl+C x3 force quit",
    ]


def format_artifact_entry(item: dict[str, Any], *, resolved_key: str = "path") -> str:
    label = str(item.get("label") or item.get("id") or "?")
    target = str(item.get(resolved_key) or item.get("path") or item.get("abs_path") or item.get("resolved_path") or "")
    if item.get("preview_only") is True:
        marker = "preview"
    else:
        exists = item.get("exists")
        marker = "ok" if exists in (True, None) else "missing"
    return f"- {label}: {target} [{marker}]"


def build_result_lines(
    locale: str,
    manifest: dict[str, Any] | None,
    view: str,
    manual_prompts: list[dict[str, str]] | None = None,
    active_mode: str = "",
    form_state: RequestFormState | None = None,
) -> list[str]:
    if active_mode == "handoff_intake":
        if view == "BASIS":
            return build_handoff_basis_lines(locale, manifest, form_state)
        if view == "REQUIREMENTS":
            return build_handoff_requirements_lines(locale, manifest, manual_prompts, form_state)
        if view == "REVIEW":
            return build_handoff_review_lines(locale, manifest)
        if view == "FEEDBACK":
            return build_handoff_feedback_lines(locale, manifest, manual_prompts)
    if not manifest:
        if view == "PROMPTS":
            return build_prompt_lines(locale, manifest, manual_prompts)
        return [tr(locale, "label.none")]

    lines: list[str] = []
    if view == "RESULTS":
        lines.append(f"{tr(locale, 'panel.result')}: mode={manifest.get('mode')} rc={manifest.get('rc')}")
        lines.append(f"Run ID: {manifest.get('run_id', '')}")
        if manifest.get("dry_run"):
            lines.append(tr(locale, "label.preview_only_result"))
        lines.append("---")
        lines.append("Primary")
        for item in manifest.get("primary_artifacts") or []:
            lines.append(format_artifact_entry(item))
        secondary = manifest.get("secondary_artifacts") or []
        if secondary:
            lines.append("---")
            lines.append("Secondary")
            for item in secondary:
                lines.append(format_artifact_entry(item))
        actions = manifest.get("next_actions") or []
        if actions:
            lines.append("---")
            lines.append(tr(locale, "label.actions"))
            for action in actions:
                lines.append(f"- {action.get('id')}: {action.get('label')}")
        return lines

    if view == "INPUTS":
        lines.append(f"{tr(locale, 'panel.request')}: mode={manifest.get('mode')}")
        req_path = manifest.get("request_manifest") or tr(locale, "label.none")
        lines.append(f"{tr(locale, 'label.request.path')}: {req_path}")
        lines.append("---")
        lines.append("Request artifacts")
        for item in manifest.get("request_artifacts") or []:
            lines.append(format_artifact_entry(item))
        lines.append("---")
        lines.append("Input artifacts")
        for item in manifest.get("input_artifacts") or []:
            lines.append(format_artifact_entry(item, resolved_key="resolved_path"))
            original = str(item.get("original_path") or "").strip()
            if original:
                lines.append(f"  original: {original}")
        return lines

    if view == "PROMPTS":
        return build_prompt_lines(locale, manifest, manual_prompts)

    return [tr(locale, "label.none")]

def parse_stage_from_run_line(text: str) -> str | None:
    m = re.search(r"\[RUN\]\s+([a-zA-Z0-9_]+)\.[a-zA-Z0-9_]+:", text)
    if not m:
        return None
    return m.group(1)


def parse_pipeline_event(text: str) -> str | None:
    m = re.search(r"^\[RUN\]\s+([a-zA-Z0-9_]+):", text)
    if m:
        return f"role_start role={m.group(1)}"

    m = re.search(r"^\[OK\]\s+([a-zA-Z0-9_]+)$", text)
    if m:
        return f"role_done role={m.group(1)}"

    m = re.search(r"^\[FAIL\]\s+([a-zA-Z0-9_]+):\s*(.*)$", text)
    if m:
        detail = m.group(2).strip() or "unknown"
        return f"role_fail role={m.group(1)} detail={detail}"

    m = re.search(r"^\[LOOP\]\s+([a-zA-Z0-9_]+)\s+iteration\s+(\d+)/(\d+):\s*(\S+)", text)
    if m:
        return f"loop role={m.group(1)} iter={m.group(2)}/{m.group(3)} case={m.group(4)}"

    return None


def build_context_hint(
    locale: str,
    running: bool,
    palette_active: bool,
    overlay_mode: str | None,
    form_state: RequestFormState | None,
    confirm_cmd: list[str] | None,
) -> str:
    if running:
        return tr(locale, "hint.running")
    if form_state is not None:
        return tr(locale, "hint.form")
    if confirm_cmd:
        return tr(locale, "hint.confirm")
    if overlay_mode:
        return tr(locale, "hint.overlay")
    if palette_active:
        return tr(locale, "hint.palette")
    return tr(locale, "hint.ready")


def safe_addnstr(win, y: int, x: int, text: str, max_len: int, attr: int = 0) -> None:
    if max_len <= 0 or y < 0 or x < 0:
        return
    try:
        height, width = win.getmaxyx()
    except curses.error:
        return
    if y >= height or x >= width:
        return
    usable = min(max_len, max(0, width - x - 1))
    if usable <= 0:
        return
    clipped = (text or "").replace("\n", " ")
    try:
        win.addnstr(y, x, clipped, usable, attr)
    except curses.error:
        try:
            win.addnstr(y, x, clipped[: max(0, usable - 1)], max(0, usable - 1), attr)
        except curses.error:
            pass


def draw_form_overlay(stdscr, locale: str, form_state: RequestFormState) -> None:
    h, w = stdscr.getmaxyx()
    box_w = min(max(72, w // 2), w - 4)
    box_h = min(max(12, len(form_state.fields) + 6), h - 4)
    y0 = max(1, (h - box_h) // 2)
    x0 = max(2, (w - box_w) // 2)
    win = stdscr.derwin(box_h, box_w, y0, x0)
    win.erase()
    win.border()
    safe_addnstr(win, 0, 2, f" {tr(locale, 'pane.form')}: {form_state.title} ", box_w - 4, curses.A_BOLD)
    mode_line = f"{tr(locale, 'label.request.mode')}: {form_state.mode} | {tr(locale, 'label.form.editing') if form_state.editing else tr(locale, 'label.form.idle')}"
    safe_addnstr(win, 1, 1, mode_line, box_w - 2)

    max_fields = box_h - 4
    start = 0
    if form_state.selected >= max_fields:
        start = form_state.selected - max_fields + 1

    for i, field in enumerate(form_state.fields[start:start + max_fields]):
        idx = start + i
        yy = 2 + i
        marker = ">" if idx == form_state.selected else " "
        label = tr(locale, field.label_key)
        suffix = tr(locale, field.status_key) if field.status_key else (tr(locale, "label.required") if field.required else tr(locale, "label.optional"))
        value = ""
        if field.kind == "action":
            value = ""
        elif form_state.editing and idx == form_state.selected:
            value = form_state.buffer
        else:
            value = form_state.values.get(field.key, "")
        value_text = value or tr(locale, "label.none")
        text = f"{marker} {label} [{suffix}]: {value_text}" if field.kind != "action" else f"{marker} {label}"
        style = curses.A_REVERSE if idx == form_state.selected else curses.A_NORMAL
        safe_addnstr(win, yy, 1, text, box_w - 2, style)

    footer = form_state.message or tr(locale, "hint.form")
    safe_addnstr(win, box_h - 1, 1, footer, box_w - 2)


def draw(
    stdscr,
    locale,
    items,
    selected,
    logs,
    dry_run,
    running,
    status,
    last_cmd,
    last_request_path,
    last_ui_manifest_path,
    palette_active,
    palette_filter,
    confirm_cmd,
    log_view,
    log_scroll,
    result_manifest,
    manual_prompts,
    runtime,
    caps,
    overlay_mode,
    overlay_items,
    overlay_selected,
    overlay_text_title,
    overlay_text_content,
    overlay_text_scroll,
    form_state,
):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    left_w = min(42, max(30, w // 3))
    hint_line = build_context_hint(locale, running, palette_active, overlay_mode, form_state, confirm_cmd)
    run_flag = "RUNNING" if running else "IDLE"
    mode_flag = "DRY-RUN" if dry_run else "REAL"
    runtime_text = (
        f"Runtime model={runtime.model or 'default'} "
        f"variant={variant_status_text(caps, runtime)}"
    )

    title = tr(locale, "title.python", lang=tr(locale, f"locale.{normalize_locale(locale)}"))
    safe_addnstr(stdscr, 0, 0, title, w - 1, curses.A_BOLD)
    safe_addnstr(stdscr, 1, 0, hint_line, w - 1)
    safe_addnstr(stdscr, 2, 0, runtime_text, w - 1)

    # left pane
    pane_title = tr(locale, "pane.palette") if palette_active else tr(locale, "pane.commands")
    safe_addnstr(stdscr, 3, 0, pane_title, left_w - 1, curses.A_UNDERLINE)
    if palette_active:
        safe_addnstr(stdscr, 4, 0, f"{tr(locale, 'label.filter')}: {palette_filter}", left_w - 1)
        list_start_y = 5
    else:
        list_start_y = 4

    for idx, item in enumerate(items):
        y = list_start_y + idx
        if y >= h - 3:
            break
        if item.kind == "section":
            text = item.title
            style = curses.A_BOLD | curses.A_UNDERLINE
        else:
            marker = ">" if idx == selected else " "
            indent = "  " * max(0, item.depth)
            text = f"{marker} {indent}{item.title}"
            style = curses.A_REVERSE if idx == selected else curses.A_NORMAL
            if item.kind == "mode":
                style |= curses.A_BOLD
        safe_addnstr(stdscr, y, 0, text, left_w - 1, style)

    current_item = items[selected] if items and 0 <= selected < len(items) else None
    active_mode = active_result_mode(result_manifest, form_state, current_item)

    # selected description
    if items and 0 <= selected < len(items):
        desc = items[selected].desc
        safe_addnstr(stdscr, h - 3, 0, f"{tr(locale, 'label.desc')}: {desc}", left_w - 1)

    # right pane
    x0 = left_w + 1
    right_w = max(1, w - x0 - 1)
    view_badge = result_view_label(locale, log_view, active_mode)

    summary_lines: list[tuple[str, int, bool]] = [
        (tr(locale, "panel.status"), curses.A_BOLD, False),
        (f"Run: {run_flag} | Dry: {mode_flag} | View: {view_badge}", curses.A_NORMAL, True),
        (status, curses.A_BOLD, True),
        ("---", curses.A_NORMAL, False),
        (tr(locale, "panel.focus"), curses.A_BOLD, False),
        (hint_line, curses.A_NORMAL, True),
        ("---", curses.A_NORMAL, False),
        (tr(locale, "panel.last"), curses.A_BOLD, False),
        (" ".join(shlex.quote(s) for s in (last_cmd or [])) or "(none)", curses.A_NORMAL, True),
    ]
    if last_request_path:
        summary_lines.extend([
            ("---", curses.A_NORMAL, False),
            (tr(locale, "label.request.path"), curses.A_BOLD, False),
            (str(last_request_path), curses.A_NORMAL, True),
        ])
    if last_ui_manifest_path:
        summary_lines.extend([
            ("---", curses.A_NORMAL, False),
            (tr(locale, "label.ui.path"), curses.A_BOLD, False),
            (str(last_ui_manifest_path), curses.A_NORMAL, True),
        ])
    if confirm_cmd:
        summary_lines.extend([
            (f"{tr(locale, 'label.confirm')}:", curses.A_BOLD, False),
            (" ".join(shlex.quote(s) for s in confirm_cmd), curses.A_NORMAL, True),
        ])
    if current_item and current_item.kind == "mode":
        outline = mode_outline_lines(locale, current_item.key)
        if outline:
            summary_lines.extend([
                ("---", curses.A_NORMAL, False),
                (tr(locale, "panel.outline"), curses.A_BOLD, False),
            ])
            summary_lines.extend((line, curses.A_NORMAL, True) for line in outline)

    rendered_summary: list[tuple[str, int]] = []
    for text, style, should_wrap in summary_lines:
        parts = wrap_display_text(text, right_w) if should_wrap else [text]
        if not parts:
            parts = [""]
        for idx, part in enumerate(parts):
            rendered_summary.append((part, style if idx == 0 else curses.A_NORMAL))

    summary_y = 4
    for idx, (line, style) in enumerate(rendered_summary):
        y = summary_y + idx
        if y >= h - 5:
            break
        safe_addnstr(stdscr, y, x0, line, right_w, style)

    separator_y = summary_y + len(rendered_summary)
    if separator_y < h - 4:
        safe_addnstr(stdscr, separator_y, x0, "-" * max(1, w - x0 - 2), right_w)

    max_log_lines = h - separator_y - 5
    visible_logs = build_visible_log_lines(locale, logs, log_view, result_manifest, manual_prompts, active_mode=active_mode, form_state=form_state)
    wrapped_visible_logs = wrap_panel_lines(visible_logs, right_w)
    show, effective_scroll, _ = slice_visible_log_lines(wrapped_visible_logs, max_log_lines, log_scroll)
    output_title = f"{tr(locale, 'pane.output')} [{view_badge}]"
    if effective_scroll > 0:
        output_title += f" [scroll={effective_scroll}]"
    safe_addnstr(stdscr, 3, x0, output_title, right_w, curses.A_UNDERLINE)
    for i, line in enumerate(show):
        y = separator_y + 1 + i
        if y >= h - 4:
            break
        safe_addnstr(stdscr, y, x0, line, right_w)

    if confirm_cmd:
        preview = " ".join(shlex.quote(s) for s in confirm_cmd)
        safe_addnstr(stdscr, h - 3, x0, f"{tr(locale, 'label.preview')}: {preview}", right_w, curses.A_BOLD)
    else:
        quick = tr(locale, "quick.keys")
        safe_addnstr(stdscr, h - 3, x0, quick, right_w)

    # status bar
    risk_state = f"DRY={'ON' if dry_run else 'OFF'}"
    bar = f"[RUN-STATE:{run_flag}] [RISK-STATE:{risk_state}] [LOG-STATE:{log_view}] {status}"
    safe_addnstr(stdscr, h - 1, 0, bar, w - 1, curses.A_REVERSE)

    if form_state is not None:
        draw_form_overlay(stdscr, locale, form_state)

    if overlay_mode:
        box_w = min(max(52, w // 2), w - 4)
        if overlay_mode == "help":
            help_lines = wrap_panel_lines(help_overlay_lines(locale), max(8, box_w - 2))
            box_h = min(max(10, len(help_lines) + 3), h - 4)
        elif overlay_mode == "prompt":
            help_lines = wrap_panel_lines((overlay_text_content or "").splitlines(), max(8, box_w - 2))
            box_h = min(max(10, min(len(help_lines), h - 8) + 3), h - 4)
        else:
            help_lines = []
            box_h = min(max(8, len(overlay_items) + 4), h - 4)
        y0 = max(1, (h - box_h) // 2)
        x0 = max(2, (w - box_w) // 2)

        win = stdscr.derwin(box_h, box_w, y0, x0)
        win.erase()
        win.border()
        if overlay_mode == "help":
            title = tr(locale, "overlay.help")
        elif overlay_mode == "prompt":
            title = overlay_text_title or tr(locale, "label.view.prompts")
        elif overlay_mode == "model":
            title = tr(locale, "overlay.model")
        elif overlay_mode == "flow":
            title = tr(locale, "overlay.flow")
        elif overlay_mode == "stage":
            title = tr(locale, "overlay.stage")
        else:
            title = tr(locale, "overlay.variant")
        safe_addnstr(win, 0, 2, f" {title} ", box_w - 4, curses.A_BOLD)

        if overlay_mode in {"help", "prompt"}:
            max_lines = box_h - 2
            start = min(max(0, overlay_text_scroll), max(0, len(help_lines) - max_lines)) if overlay_mode == "prompt" else 0
            for i, line in enumerate(help_lines[start:start + max_lines]):
                safe_addnstr(win, 1 + i, 1, line, box_w - 2)
        else:
            max_items = box_h - 3
            start = 0
            if overlay_selected >= max_items:
                start = overlay_selected - max_items + 1

            for i, item in enumerate(overlay_items[start:start + max_items]):
                idx = start + i
                yy = 1 + i
                marker = ">" if idx == overlay_selected else " "
                text = f"{marker} {item.label}"
                style = curses.A_REVERSE if idx == overlay_selected else curses.A_NORMAL
                if not item.enabled:
                    style |= curses.A_DIM
                safe_addnstr(win, yy, 1, text, box_w - 2, style)

            safe_addnstr(win, box_h - 1, 1, tr(locale, "overlay.actions"), box_w - 2)
    stdscr.refresh()


def filter_menu_items(all_items: list[MenuItem], text: str) -> list[MenuItem]:
    q = text.strip().lower()
    selectable = [it for it in all_items if it.selectable]
    if not q:
        return selectable

    if q.startswith("mode:") or q.startswith("request:"):
        key = q.split(":", 1)[1].strip()
        return [
            it
            for it in selectable
            if it.kind == "mode" and key in it.key.lower()
        ]

    if q.startswith("tool:"):
        key = q.split(":", 1)[1].strip()
        return [it for it in selectable if it.kind == "tool" and key in it.key.lower()]

    if q.startswith("advanced:") or q.startswith("flow:"):
        key = q.split(":", 1)[1].strip()
        return [it for it in selectable if it.kind == "advanced" and key in it.key.lower()]

    return [
        it
        for it in selectable
        if q in it.title.lower() or q in it.desc.lower() or q in it.key.lower()
    ]


def open_request_form_for_item(cfg: dict[str, Any], locale: str, item: MenuItem) -> RequestFormState | None:
    if item.kind == "mode":
        return build_request_form(cfg, locale, item.key)
    return None


def arm_quit(locale: str, running: bool, quit_presses: int, quit_deadline: float, now: float | None = None) -> tuple[bool, int, float, str]:
    current = now if now is not None else time.monotonic()
    if quit_deadline <= 0 or current > quit_deadline:
        quit_presses = 0
    quit_presses += 1
    quit_deadline = current + 2.0
    remain = 3 - quit_presses
    if remain <= 0:
        return True, 0, 0.0, ""
    key = "status.quit.running" if running else "status.quit.idle"
    return False, quit_presses, quit_deadline, tr(locale, key, remain=remain)


def run_tui(project_root: Path, config_rel: str, lang: str | None = None) -> int:
    cfg = load_runner_config(project_root, config_rel)
    locale = resolve_locale(cfg, lang)
    all_items = build_menu_items(cfg, locale)
    items = all_items
    if not items:
        print("[ERR] no menu items found")
        return EXIT_FAIL

    runner = [sys.executable, str((project_root / "scripts/runner.py").resolve())]
    capabilities = load_capabilities(project_root)
    pending_sigint = [0]

    def _sigint_handler(signum, frame):
        del signum, frame
        pending_sigint[0] += 1

    def _curses_main(stdscr):
        nonlocal locale, all_items
        curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.timeout(120)

        items = all_items
        selected = first_selectable_index(items)
        dry_run = False
        palette_active = False
        palette_filter = ""
        confirm_cmd: Optional[list[str]] = None
        log_view = "ALL"  # ALL | OUT | ERR | RESULTS | INPUTS | PROMPTS | BASIS | REQUIREMENTS | REVIEW | FEEDBACK
        log_scroll = 0
        logs = [tr(locale, "log.ready")]
        status = tr(locale, "status.select")
        ps: Optional[ProcessStreamer] = None
        last_cmd: list[str] = []
        last_request_path: Optional[Path] = None
        last_ui_manifest_path: Optional[Path] = None
        result_manifest: dict[str, Any] | None = None
        manual_prompts: list[dict[str, str]] = []
        runtime = RuntimeState()
        overlay_mode: Optional[str] = None  # help | model | variant | flow | stage
        overlay_items: list[OverlayItem] = []
        overlay_selected = 0
        overlay_text_title = ""
        overlay_text_content = ""
        overlay_text_scroll = 0
        form_state: RequestFormState | None = None
        last_failed_stage: Optional[str] = None
        current_stage: Optional[str] = None
        quit_presses = 0
        quit_deadline = 0.0

        while True:
            running = ps is not None and not ps.done.is_set()
            now = time.monotonic()
            if quit_deadline > 0 and now > quit_deadline:
                quit_presses = 0
                quit_deadline = 0.0

            # drain logs
            if ps is not None:
                while True:
                    try:
                        tag, line = ps.q.get_nowait()
                    except queue.Empty:
                        break
                    prefix = "[E]" if tag == "ERR" else "[O]"
                    logs.append(f"{prefix} {line}")
                    st = parse_stage_from_run_line(line)
                    if st:
                        current_stage = st

                    manifest_path = parse_manifest_path(line)
                    if manifest_path is not None:
                        last_ui_manifest_path = manifest_path
                        loaded = load_ui_manifest(manifest_path)
                        if loaded is not None:
                            result_manifest = loaded
                            manual_prompts = []
                            status = f"Loaded ui manifest: {manifest_path.name}"

                    evt = parse_pipeline_event(line)
                    if evt:
                        logs.append(f"[SYS] EVT {evt}")

                    if len(logs) > 2000:
                        logs = logs[-1200:]

                if ps.done.is_set():
                    rc = ps.rc if ps.rc is not None else -1
                    logs.append(f"[SYS] command done, rc={rc}")
                    if rc == 0:
                        status = "SUCCESS"
                    else:
                        last_failed_stage = current_stage
                        if last_failed_stage:
                            status = f"FAILED rc={rc}, stage: {last_failed_stage} (Shift+F to rerun)"
                        else:
                            status = f"FAILED rc={rc}"
                    current_stage = None
                    ps = None

            draw(
                stdscr,
                locale,
                items,
                selected,
                logs,
                dry_run,
                running,
                status,
                last_cmd,
                last_request_path,
                last_ui_manifest_path,
                palette_active,
                palette_filter,
                confirm_cmd,
                log_view,
                log_scroll,
                result_manifest,
                manual_prompts,
                runtime,
                capabilities,
                overlay_mode,
                overlay_items,
                overlay_selected,
                overlay_text_title,
                overlay_text_content,
                overlay_text_scroll,
                form_state,
            )
            ch = stdscr.getch()
            if pending_sigint[0] > 0:
                pending_sigint[0] -= 1
                ch = 3

            if ch == -1:
                continue

            if ch != 3 and quit_presses > 0:
                quit_presses = 0
                quit_deadline = 0.0

            if ch == 3:
                should_quit, quit_presses, quit_deadline, quit_status = arm_quit(
                    locale,
                    running,
                    quit_presses,
                    quit_deadline,
                    now=time.monotonic(),
                )
                if should_quit:
                    if ps is not None and ps.proc and ps.proc.poll() is None:
                        try:
                            ps.proc.kill()
                        except Exception:
                            pass
                    break
                status = quit_status
                continue

            if ch == ord("?"):
                if overlay_mode == "help":
                    overlay_mode = None
                    overlay_items = []
                    overlay_selected = 0
                    overlay_text_title = ""
                    overlay_text_content = ""
                    overlay_text_scroll = 0
                    status = "Overlay closed"
                else:
                    overlay_mode = "help"
                    overlay_items = []
                    overlay_selected = 0
                    overlay_text_title = ""
                    overlay_text_content = ""
                    overlay_text_scroll = 0
                    status = "Help overlay open"
                    confirm_cmd = None
                continue

            if overlay_mode == "prompt":
                if ch in (27,):
                    overlay_mode = None
                    overlay_text_title = ""
                    overlay_text_content = ""
                    overlay_text_scroll = 0
                    status = "Overlay closed"
                    continue
                if ch in (ord("y"), ord("Y")):
                    status = copy_text_to_clipboard(project_root, overlay_text_content, overlay_text_title or "prompt")
                    continue
                if ch in (curses.KEY_UP, ord("k")):
                    overlay_text_scroll = max(0, overlay_text_scroll - 3)
                    continue
                if ch in (curses.KEY_DOWN, ord("j")):
                    overlay_text_scroll += 3
                    continue
                continue

            if form_state is not None:
                field = form_state.fields[form_state.selected]
                if form_state.editing:
                    if ch in (27,):
                        form_state.editing = False
                        form_state.buffer = ""
                        form_state.message = "Edit cancelled"
                        continue
                    if ch == 9:
                        if is_path_field(field):
                            updated, message = complete_path_input(project_root, form_state.buffer, locale)
                            if updated is not None:
                                form_state.buffer = updated
                            form_state.message = message
                        else:
                            form_state.message = tr(locale, "status.path_complete.disabled")
                        continue
                    if ch in (10, 13):
                        form_state.values[field.key] = form_state.buffer.strip()
                        form_state.editing = False
                        form_state.message = f"{field.key} updated"
                        continue
                    if ch in (curses.KEY_BACKSPACE, 127, 8):
                        form_state.buffer = form_state.buffer[:-1]
                        continue
                    if 32 <= ch <= 126:
                        form_state.buffer += chr(ch)
                        continue
                else:
                    if ch in (27,):
                        form_state = None
                        status = "Request form closed"
                        continue
                    if ch in (curses.KEY_UP, ord("k")):
                        form_state.selected = (form_state.selected - 1) % len(form_state.fields)
                        continue
                    if ch in (curses.KEY_DOWN, ord("j")):
                        form_state.selected = (form_state.selected + 1) % len(form_state.fields)
                        continue
                    if ch in (curses.KEY_LEFT, ord("h")) and field.kind == "choice":
                        form_state.values[field.key] = cycle_choice(field.choices, form_state.values.get(field.key, ""), -1)
                        continue
                    if ch in (curses.KEY_RIGHT, ord("l")) and field.kind == "choice":
                        form_state.values[field.key] = cycle_choice(field.choices, form_state.values.get(field.key, ""), 1)
                        continue
                    if ch in (10, 13):
                        if field.kind == "text":
                            form_state.editing = True
                            form_state.buffer = form_state.values.get(field.key, "")
                            if is_path_field(field):
                                base_dir, _ = path_completion_base(project_root, form_state.buffer)
                                form_state.message = tr(locale, "status.path_base", base=str(base_dir))
                            else:
                                form_state.message = f"Editing {field.key}"
                            continue
                        if field.kind == "choice":
                            form_state.values[field.key] = cycle_choice(field.choices, form_state.values.get(field.key, ""))
                            continue
                        if field.kind == "action":
                            if field.action == "cancel":
                                form_state = None
                                status = "Request form cancelled"
                                continue
                            if field.action == "preview_requirements":
                                prompt_text = requirements_prompt_text(form_state.values.get("target_state", ""))
                                overlay_mode = "prompt"
                                overlay_items = []
                                overlay_selected = 0
                                overlay_text_title = tr(locale, "label.request.preview_requirements")
                                overlay_text_content = prompt_text
                                overlay_text_scroll = 0
                                status = "Intake contract preview open"
                                continue
                            if field.action == "copy_requirements":
                                prompt_text = requirements_prompt_text(form_state.values.get("target_state", ""))
                                status = copy_text_to_clipboard(project_root, prompt_text, "handoff intake contract")
                                continue
                            if field.action == "submit":
                                err = validate_request_form(form_state)
                                if err:
                                    form_state.message = err
                                    status = err
                                    continue
                                session_id = session_id_hint_for_form(project_root, form_state) or dt.datetime.now().strftime(
                                    f"tui_{form_state.mode}_%Y%m%d_%H%M%S_%f"
                                )
                                payload = create_request_manifest_payload(
                                    form_state,
                                    session_id=session_id,
                                    dry_run=dry_run,
                                    runtime=runtime,
                                )
                                manifest_path = write_request_manifest(project_root, payload)
                                cmd = build_request_cmd(runner, manifest_path, runtime)
                                ps = ProcessStreamer(cmd=cmd, cwd=project_root)
                                ps.start()
                                last_cmd = cmd
                                last_request_path = manifest_path
                                last_ui_manifest_path = None
                                result_manifest = None
                                manual_prompts = []
                                log_scroll = 0
                                form_state = None
                                confirm_cmd = None
                                status = f"RUNNING request {payload['mode']}"
                                logs.append(f"[SYS] request manifest: {manifest_path}")
                                logs.append(f"[SYS] start: {' '.join(shlex.quote(x) for x in cmd)}")
                                continue
                continue

            if overlay_mode:
                if ch in (27,):
                    overlay_mode = None
                    overlay_items = []
                    overlay_selected = 0
                    overlay_text_title = ""
                    overlay_text_content = ""
                    overlay_text_scroll = 0
                    status = "Overlay closed"
                    continue
                if ch in (curses.KEY_UP, ord("k")) and overlay_items:
                    overlay_selected = (overlay_selected - 1) % len(overlay_items)
                    continue
                if ch in (curses.KEY_DOWN, ord("j")) and overlay_items:
                    overlay_selected = (overlay_selected + 1) % len(overlay_items)
                    continue
                if ch in (10, 13) and overlay_items:
                    item = overlay_items[overlay_selected]
                    if not item.enabled:
                        status = "Option unavailable (disabled by capability probe)"
                        continue
                    if item.kind == "model":
                        runtime.model = item.value or None
                        runtime.variant = default_variant_for_model(capabilities, runtime.model)
                        family = model_family(capabilities, runtime.model)
                        variant_text = variant_status_text(capabilities, runtime)
                        if runtime.model and family == "gemini":
                            status = f"Model set to: {runtime.model} | variant: n/a"
                        elif runtime.model:
                            status = f"Model set to: {runtime.model} | variant: {variant_text}"
                        else:
                            status = "Model set to: default"
                        confirm_cmd = None
                    elif item.kind == "variant":
                        runtime.variant = item.value or None
                        status = f"Variant set to: {variant_status_text(capabilities, runtime)}"
                        confirm_cmd = None
                    elif item.kind == "flow":
                        cmd = build_runner_cmd(runner, ["run", item.value], dry_run, runtime)
                        ps = ProcessStreamer(cmd=cmd, cwd=project_root)
                        ps.start()
                        last_cmd = cmd
                        log_scroll = 0
                        status = f"RUNNING flow {item.value}"
                        logs.append(f"[SYS] direct flow run: {' '.join(shlex.quote(x) for x in cmd)}")
                    elif item.kind == "stage":
                        cmd = build_runner_cmd(runner, ["stage", item.value], dry_run, runtime)
                        ps = ProcessStreamer(cmd=cmd, cwd=project_root)
                        ps.start()
                        last_cmd = cmd
                        log_scroll = 0
                        status = f"RUNNING stage {item.value}"
                        logs.append(f"[SYS] stage quick run: {' '.join(shlex.quote(x) for x in cmd)}")
                    overlay_mode = None
                    overlay_items = []
                    overlay_selected = 0
                    overlay_text_title = ""
                    overlay_text_content = ""
                    overlay_text_scroll = 0
                    continue

            # palette text input mode
            if palette_active and ch not in (27, 10, 13, curses.KEY_UP, curses.KEY_DOWN, ord("j"), ord("k"), 11, 15, 19, 20, ord("F"), ord("?")):
                if ch in (curses.KEY_BACKSPACE, 127, 8):
                    palette_filter = palette_filter[:-1]
                elif 32 <= ch <= 126:
                    palette_filter += chr(ch)
                items = filter_menu_items(all_items, palette_filter)
                selected = first_selectable_index(items)
                status = f"Palette filter: {palette_filter or '(empty)'}"
                continue

            if ch in (ord("q"),):
                status = tr(locale, "status.quit.q_only")
            elif ch == 27:  # ESC
                if confirm_cmd is not None:
                    confirm_cmd = None
                    status = "Confirmation cancelled"
                elif palette_active:
                    palette_active = False
                    palette_filter = ""
                    items = all_items
                    selected = first_selectable_index(items)
                    status = "Palette closed"
                else:
                    status = tr(locale, "status.quit.esc_only")
            elif ch in (ord("/"), 11):  # / or Ctrl+K
                palette_active = not palette_active
                if palette_active:
                    palette_filter = ""
                    items = filter_menu_items(all_items, palette_filter)
                    selected = first_selectable_index(items)
                    status = "Palette open (/ or Ctrl+K, supports mode:/tool:/advanced: filters)"
                else:
                    items = all_items
                    selected = first_selectable_index(items)
                    status = "Palette closed"
            elif ch in (ord("l"), ord("L")):
                current = items[selected] if items and 0 <= selected < len(items) else None
                locale = toggle_locale(locale)
                all_items = build_menu_items(cfg, locale)
                items = filter_menu_items(all_items, palette_filter) if palette_active else all_items
                selected = restore_selection(items, current)
                if overlay_mode == "flow":
                    overlay_items = build_flow_overlay_items(cfg, locale)
                    overlay_selected = min(overlay_selected, max(0, len(overlay_items) - 1))
                elif overlay_mode == "stage":
                    overlay_items = build_stage_overlay_items(cfg, locale)
                    overlay_selected = min(overlay_selected, max(0, len(overlay_items) - 1))
                status = tr(locale, "status.language", lang=tr(locale, f"locale.{locale}"))
                confirm_cmd = None
            elif ch == 15:  # Ctrl+O
                if ps is not None and not ps.done.is_set():
                    status = "Cannot switch model while a command is running"
                    continue
                overlay_mode = "model"
                overlay_items = build_model_overlay_items(capabilities)
                overlay_selected = 0
                status = "Model overlay open"
                confirm_cmd = None
            elif ch == 20:  # Ctrl+T
                if ps is not None and not ps.done.is_set():
                    status = "Cannot switch variant while a command is running"
                    continue
                overlay_mode = "variant"
                overlay_items = build_variant_overlay_items(capabilities, runtime.model)
                overlay_selected = 0
                status = "Variant overlay open" if runtime.model else "Select a model before opening variant"
                confirm_cmd = None
            elif ch == 19:  # Ctrl+S
                if ps is not None and not ps.done.is_set():
                    status = "Cannot quick-run a stage while a command is running"
                    continue
                overlay_mode = "stage"
                overlay_items = build_stage_overlay_items(cfg, locale)
                overlay_selected = 0
                status = "Stage overlay open"
                confirm_cmd = None
            elif ch == ord("F"):  # Shift+F
                if ps is not None and not ps.done.is_set():
                    status = "Cannot rerun failed stage while a command is running"
                    continue
                if not last_failed_stage:
                    status = "No failed stage available for rerun"
                    continue
                cmd = build_runner_cmd(runner, ["stage", last_failed_stage], dry_run, runtime)
                ps = ProcessStreamer(cmd=cmd, cwd=project_root)
                ps.start()
                last_cmd = cmd
                log_scroll = 0
                status = f"RUNNING rerun failed stage {last_failed_stage}"
                logs.append(f"[SYS] rerun failed stage: {' '.join(shlex.quote(x) for x in cmd)}")
            elif ch == 24:  # Ctrl+X
                if ps is not None and not ps.done.is_set():
                    ps.kill()
                    status = "Stop requested (Ctrl+X)"
                else:
                    status = "No command is currently running"
            elif ch in (curses.KEY_UP, ord("k")) and items:
                selected = next_selectable_index(items, selected, -1)
            elif ch in (curses.KEY_DOWN, ord("j")) and items:
                selected = next_selectable_index(items, selected, 1)
            elif ch in (10, 13):
                if ps is not None and not ps.done.is_set():
                    status = "Command is running; wait or press Ctrl+X to stop"
                    continue
                if not items:
                    status = "No matching command; adjust the palette filter"
                    continue

                item = items[selected]
                if item.kind == "mode":
                    form_state = open_request_form_for_item(cfg, locale, item)
                    confirm_cmd = None
                    status = f"Opened request form: {item.key}"
                    continue
                if item.kind == "advanced":
                    confirm_cmd = None
                    action = item.args[0] if item.args else ""
                    if action == "direct_flow":
                        overlay_mode = "flow"
                        overlay_items = build_flow_overlay_items(cfg, locale)
                        overlay_selected = 0
                        status = "Direct flow overlay open"
                    elif action == "stage_quick_run":
                        overlay_mode = "stage"
                        overlay_items = build_stage_overlay_items(cfg, locale)
                        overlay_selected = 0
                        status = "Stage overlay open"
                    elif action == "rerun_failed_stage":
                        if not last_failed_stage:
                            status = "No failed stage available for rerun"
                            continue
                        cmd = build_runner_cmd(runner, ["stage", last_failed_stage], dry_run, runtime)
                        ps = ProcessStreamer(cmd=cmd, cwd=project_root)
                        ps.start()
                        last_cmd = cmd
                        log_scroll = 0
                        status = f"RUNNING rerun failed stage {last_failed_stage}"
                        logs.append(f"[SYS] rerun failed stage: {' '.join(shlex.quote(x) for x in cmd)}")
                    continue
                if item.kind != "tool":
                    status = "Selected entry is informational only"
                    continue
                cmd = build_runner_cmd(runner, item.args, dry_run, runtime)

                if confirm_cmd is None:
                    confirm_cmd = cmd
                    status = "Confirm armed: press Enter again to execute, Esc cancels"
                    continue

                if confirm_cmd != cmd:
                    confirm_cmd = cmd
                    status = "Confirm updated: press Enter again to execute"
                    continue

                ps = ProcessStreamer(cmd=cmd, cwd=project_root)
                ps.start()
                last_cmd = cmd
                log_scroll = 0
                confirm_cmd = None
                status = f"RUNNING {item.title}"
                logs.append(f"[SYS] start: {' '.join(shlex.quote(x) for x in cmd)}")
            elif ch == ord("v"):
                current_item = items[selected] if items and 0 <= selected < len(items) else None
                active_mode = active_result_mode(result_manifest, form_state, current_item)
                order = available_result_views(active_mode)
                idx = order.index(log_view) if log_view in order else 0
                log_view = order[(idx + 1) % len(order)]
                log_scroll = 0
                status = f"View: {result_view_label(locale, log_view, active_mode)}"
            elif ch in (ord("y"), ord("Y")):
                current_item = items[selected] if items and 0 <= selected < len(items) else None
                active_mode = active_result_mode(result_manifest, form_state, current_item)
                prompt_entry: dict[str, str] | None
                if active_mode == "handoff_intake":
                    if log_view == "REQUIREMENTS":
                        prompt_entry = select_prompt_entry(result_manifest, manual_prompts, ("handoff_requirements_prompt",))
                        if prompt_entry is None and form_state is not None and form_state.mode == "handoff_intake":
                            prompt_entry = {
                                "id": "handoff_requirements_prompt",
                                "label": "handoff_requirements_prompt.txt",
                                "content": requirements_prompt_text(form_state.values.get("target_state", "")),
                            }
                    elif log_view == "FEEDBACK":
                        prompt_entry = select_prompt_entry(
                            result_manifest,
                            manual_prompts,
                            ("handoff_semantic_repair_prompt", "handoff_contract_repair_prompt", "handoff_repair_prompt"),
                        )
                    else:
                        status = "Switch to REQUIREMENTS or FEEDBACK view before copying a prompt"
                        continue
                else:
                    if log_view != "PROMPTS":
                        status = "Switch to PROMPTS view before copying a prompt"
                        continue
                    prompt_entry = preferred_prompt_to_copy(result_manifest, manual_prompts)
                if prompt_entry is None:
                    status = "No prompt content available to copy"
                    continue
                status = copy_text_to_clipboard(project_root, prompt_entry.get("content", ""), prompt_entry.get("label", "prompt"))
            elif ch == getattr(curses, "KEY_SR", -1):
                log_scroll += 3
                status = f"log scroll=+{log_scroll}"
            elif ch == getattr(curses, "KEY_SF", -1):
                log_scroll = max(0, log_scroll - 3)
                status = "log scroll=bottom" if log_scroll == 0 else f"log scroll=+{log_scroll}"
            elif ch == ord("d"):
                status = "Use Shift+D to toggle dry-run"
            elif ch == ord("D"):
                dry_run = not dry_run
                status = f"dry-run={'ON' if dry_run else 'OFF'}"
                confirm_cmd = None
            elif ch == ord("c"):
                logs = ["(cleared)"]
                log_scroll = 0
                status = "Output cleared"
            elif ch == ord("r"):
                if not last_cmd:
                    status = "No previous command to rerun"
                    continue
                if ps is not None and not ps.done.is_set():
                    status = "Cannot rerun while a command is running"
                    continue
                ps = ProcessStreamer(cmd=last_cmd, cwd=project_root)
                ps.start()
                log_scroll = 0
                status = "RUNNING rerun last command"
                logs.append(f"[SYS] rerun: {' '.join(shlex.quote(x) for x in last_cmd)}")

    previous_sigint = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, _sigint_handler)
    try:
        curses.wrapper(_curses_main)
    except KeyboardInterrupt:
        return EXIT_OK
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
    return EXIT_OK


def run_logic_smoke(project_root: Path) -> int:
    all_items_en = load_items(project_root, "config/runner.json", "en")
    all_items_zh = load_items(project_root, "config/runner.json", "zh")

    if not any(it.kind == "mode" and it.key == "spec_flow" for it in all_items_en):
        print("[FAIL] mode item spec_flow missing")
        return EXIT_FAIL
    if not any(it.kind == "mode" and it.key == "handoff_intake" for it in all_items_zh):
        print("[FAIL] mode item handoff_intake missing")
        return EXIT_FAIL

    mode_items = filter_menu_items(all_items_zh, "mode:verify")
    if not any(it.kind == "mode" and it.key == "incremental_verify_ready" for it in mode_items):
        print("[FAIL] palette filter mode:verify missing incremental_verify_ready")
        return EXIT_FAIL

    tool_items = filter_menu_items(all_items_zh, "tool:doctor")
    if not any(it.kind == "tool" and it.key == "doctor" for it in tool_items):
        print("[FAIL] palette filter tool:doctor missing doctor")
        return EXIT_FAIL

    advanced_items = filter_menu_items(all_items_en, "advanced:direct")
    if not any(it.kind == "advanced" and it.key == "advanced.direct_flow" for it in advanced_items):
        print("[FAIL] palette filter advanced:direct missing direct_flow")
        return EXIT_FAIL

    outline_en = mode_outline_lines("en", "spec_flow")
    outline_zh = mode_outline_lines("zh", "spec_flow")
    if not outline_en or not outline_zh or outline_en[1] == outline_zh[1]:
        print("[FAIL] locale switch did not change outline label for spec_flow")
        return EXIT_FAIL

    cmd = build_runner_cmd(["python3", "scripts/runner.py"], ["run", "plan"], True, RuntimeState(model="m1", variant="v1"))
    expected_tail = ["--dry-run", "--model", "m1", "--variant", "v1"]
    if cmd[-len(expected_tail):] != expected_tail:
        print("[FAIL] runtime override command build failed")
        return EXIT_FAIL

    cfg = load_runner_config(project_root, "config/runner.json")
    form = build_request_form(cfg, "zh", "spec_flow")
    form.values["spec_source"] = "cocotb_ex/ai_cli_pipeline/examples/incremental_manifestless/spec.md"
    payload = create_request_manifest_payload(
        form,
        session_id="tui_logic_spec",
        dry_run=True,
        runtime=RuntimeState(model="m2", variant="v2"),
    )
    if payload["mode"] != "spec_flow" or payload["execution"]["mode"] != "plan":
        print("[FAIL] request payload generation failed")
        return EXIT_FAIL
    manifest_path = write_request_manifest(project_root, payload)
    if not manifest_path.exists():
        print("[FAIL] request manifest write failed")
        return EXIT_FAIL
    request_cmd = build_request_cmd(["python3", "scripts/runner.py"], manifest_path, RuntimeState(model="m2", variant="v2"))
    expected_request = ["request", "--request-manifest", str(manifest_path), "--model", "m2", "--variant", "v2"]
    if request_cmd[-len(expected_request):] != expected_request:
        print("[FAIL] request command build failed")
        return EXIT_FAIL

    if open_request_form_for_item(cfg, "en", MenuItem("spec_flow", "mode", "Spec Flow", [], "")) is None:
        print("[FAIL] mode item did not open request form")
        return EXIT_FAIL

    flow_overlay = build_flow_overlay_items(cfg, "en")
    if not any(it.kind == "flow" and it.value == "all" for it in flow_overlay):
        print("[FAIL] direct flow overlay missing flow=all")
        return EXIT_FAIL

    backend_stage_overlay = build_stage_overlay_items(cfg, "en")
    if not any(it.kind == "stage" and it.value == "precheck" for it in backend_stage_overlay):
        print("[FAIL] stage quick-run overlay missing stage=precheck")
        return EXIT_FAIL

    help_lines = help_overlay_lines("en")
    if not help_lines or "Press ? or Esc to close" not in help_lines[0]:
        print("[FAIL] help overlay lines missing")
        return EXIT_FAIL

    class _FakeWindow:
        def getmaxyx(self):
            return (4, 12)

        def addnstr(self, y, x, text, n, attr=0):
            del y, x, text, n, attr
            raise curses.error

    try:
        safe_addnstr(_FakeWindow(), 1, 1, "0123456789abcdef", 10)
    except Exception as exc:
        print(f"[FAIL] safe_addnstr should swallow curses.error: {exc}")
        return EXIT_FAIL

    completed_spec, message = complete_path_input(project_root, "cocotb_ex/ai_cli_pipeline/examples/incremental_manifestless/sp", "en")
    expected_spec = "cocotb_ex/ai_cli_pipeline/examples/incremental_manifestless/spec.md"
    if completed_spec != expected_spec or "completed" not in message.lower():
        print("[FAIL] path completion failed for spec_source")
        return EXIT_FAIL

    completed_dir, message = complete_path_input(project_root, "cocotb_ex/ai_cli_pipeline/examples/incremental_man", "en")
    expected_dir = "cocotb_ex/ai_cli_pipeline/examples/incremental_manifestless/"
    if completed_dir != expected_dir or "completed" not in message.lower():
        print("[FAIL] path completion failed for handoff_root-like directory")
        return EXIT_FAIL

    sample_logs = [f"line-{idx}" for idx in range(10)]
    show, effective_scroll, max_scroll = slice_visible_log_lines(sample_logs, 4, 3)
    if show != ["line-3", "line-4", "line-5", "line-6"] or effective_scroll != 3 or max_scroll != 6:
        print("[FAIL] log scroll slicing failed")
        return EXIT_FAIL

    wrapped_path = wrap_display_text("/tmp/very/long/path/to/verify/report.md", 10)
    if "".join(wrapped_path) != "/tmp/very/long/path/to/verify/report.md":
        print("[FAIL] path wrapping lost content")
        return EXIT_FAIL

    wrapped_results = wrap_panel_lines(
        build_result_lines(
            "en",
            {
                "mode": "spec_flow",
                "rc": 0,
                "run_id": "run_test",
                "primary_artifacts": [
                    {
                        "label": "verify_report",
                        "path": "/tmp/very/long/path/to/verify/report.md",
                        "exists": True,
                    }
                ],
            },
            "RESULTS",
        ),
        12,
    )
    if "/tmp/very/long/path/to/verify/report.md" not in "".join(wrapped_results):
        print("[FAIL] result view wrapping lost artifact path")
        return EXIT_FAIL

    should_quit, presses, deadline, message = arm_quit("en", False, 0, 0.0, now=100.0)
    if should_quit or presses != 1 or deadline <= 100.0 or "Ctrl+C" not in message:
        print("[FAIL] first Ctrl+C arming semantics failed")
        return EXIT_FAIL
    should_quit, presses, deadline, _ = arm_quit("en", False, presses, deadline, now=101.0)
    if should_quit or presses != 2:
        print("[FAIL] second Ctrl+C arming semantics failed")
        return EXIT_FAIL
    should_quit, presses, deadline, _ = arm_quit("en", False, presses, deadline, now=101.5)
    if not should_quit or presses != 0 or deadline != 0.0:
        print("[FAIL] third Ctrl+C quit semantics failed")
        return EXIT_FAIL
    should_quit, presses, deadline, _ = arm_quit("en", False, 2, 50.0, now=53.1)
    if should_quit or presses != 1 or deadline <= 53.1:
        print("[FAIL] Ctrl+C timeout reset semantics failed")
        return EXIT_FAIL

    print("[OK] logic smoke passed")
    return EXIT_OK


def run_smoke(project_root: Path) -> int:
    runner = [sys.executable, str((project_root / "scripts/runner.py").resolve())]
    tests = [
        runner + ["list"],
        runner + ["run", "plan", "--dry-run"],
        runner + ["doctor", "--dry-run"],
        runner + ["request", "--request-manifest", "artifacts/protocol/examples/request_spec_flow.json", "--dry-run"],
    ]

    for cmd in tests:
        print("[SMOKE]", " ".join(shlex.quote(x) for x in cmd))
        env = dict(os.environ)
        env["CHIPFLOW_SKIP_QUOTA_GUARD"] = "1"
        proc = subprocess.run(cmd, cwd=str(project_root), text=True, capture_output=True, env=env)
        if proc.returncode != 0:
            print(proc.stdout)
            print(proc.stderr)
            print(f"[FAIL] rc={proc.returncode}")
            return EXIT_FAIL

    log_root = project_root / ".runner_logs"
    if not log_root.exists():
        print("[FAIL] missing .runner_logs after smoke")
        return EXIT_FAIL

    rc = run_logic_smoke(project_root)
    if rc != EXIT_OK:
        return rc

    print("[OK] TUI smoke passed")
    return EXIT_OK


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="chipflow terminal tui")
    p.add_argument("--config", default="config/runner.json", help="runner config path")
    p.add_argument("--lang", choices=SUPPORTED_LOCALES, help="ui language override")
    p.add_argument("--smoke-test", action="store_true", help="headless validation")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    args = parse_args(argv)
    project_root = Path(__file__).resolve().parents[1]

    if args.smoke_test:
        return run_smoke(project_root)

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("[ERR] TUI requires TTY. Use --smoke-test for headless validation.")
        return EXIT_FAIL

    return run_tui(project_root, args.config, args.lang)


if __name__ == "__main__":
    raise SystemExit(main())
