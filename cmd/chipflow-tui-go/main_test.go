package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	tea "github.com/charmbracelet/bubbletea"
)

func sampleRunnerConfig() runnerConfig {
	return runnerConfig{
		Flows: map[string][]string{
			"plan":                     {"precheck", "plan"},
			"all":                      {"precheck", "plan", "implement"},
			"handoff_intake":           {"handoff_intake"},
			"incremental_verify_ready": {"incremental_verify_ready"},
		},
		Stages: map[string]stageConfig{
			"precheck":                 {Description: "Environment checks"},
			"plan":                     {Description: "Planning"},
			"handoff_intake":           {Description: "Handoff intake"},
			"incremental_verify_ready": {Description: "Incremental verify-ready"},
		},
		UI: runnerUI{
			DefaultLocale: "zh",
			Commands: map[string]uiEntry{
				"doctor": {Title: localizedText{"en": "Environment Check", "zh": "环境检查"}},
				"list":   {Title: localizedText{"en": "List Flows / Stages", "zh": "查看 Flows / Stages"}},
			},
			RequestModes: map[string]uiEntry{
				"spec_flow":                {Title: localizedText{"en": "Spec Flow", "zh": "Spec Flow"}},
				"handoff_intake":           {Title: localizedText{"en": "Handoff Intake", "zh": "Handoff Intake"}},
				"incremental_verify_ready": {Title: localizedText{"en": "Verify-Ready Handoff", "zh": "Verify-Ready Handoff"}},
			},
			Flows: map[string]uiEntry{
				"plan":                     {Title: localizedText{"en": "Plan", "zh": "Plan"}},
				"all":                      {Title: localizedText{"en": "All", "zh": "All"}},
				"handoff_intake":           {Title: localizedText{"en": "Handoff Intake", "zh": "Handoff Intake"}},
				"incremental_verify_ready": {Title: localizedText{"en": "Verify-Ready Handoff", "zh": "Verify-Ready Handoff"}},
			},
			Stages: map[string]uiEntry{
				"precheck": {Title: localizedText{"en": "Precheck", "zh": "前置检查"}},
				"plan":     {Title: localizedText{"en": "Plan", "zh": "规划"}},
			},
		},
	}
}

func TestBuildMenuItemsLocalized(t *testing.T) {
	cfg := sampleRunnerConfig()
	enItems := buildMenuItems(cfg, "en")
	zhItems := buildMenuItems(cfg, "zh")
	if len(enItems) == 0 || len(zhItems) == 0 {
		t.Fatalf("expected localized menu items")
	}

	var enSpec, zhSpec *menuItem
	for i := range enItems {
		if enItems[i].Kind == "mode" && enItems[i].Key == "spec_flow" {
			enSpec = &enItems[i]
			break
		}
	}
	for i := range zhItems {
		if zhItems[i].Kind == "tool" && zhItems[i].Key == "doctor" {
			zhSpec = &zhItems[i]
			break
		}
	}
	if enSpec == nil {
		t.Fatalf("missing mode=spec_flow")
	}
	if zhSpec == nil {
		t.Fatalf("missing tool=doctor")
	}
	if zhSpec.Title == "Environment Check" {
		t.Fatalf("expected locale-specific tool title, got %q", zhSpec.Title)
	}
}

func TestFilterMenuItemsUsesStableKinds(t *testing.T) {
	cfg := sampleRunnerConfig()
	items := buildMenuItems(cfg, "zh")

	modeItems := filterMenuItems(items, "mode:verify")
	if len(modeItems) != 1 || modeItems[0].Key != "incremental_verify_ready" || modeItems[0].Kind != "mode" {
		t.Fatalf("mode filter mismatch: %#v", modeItems)
	}

	toolItems := filterMenuItems(items, "tool:doctor")
	if len(toolItems) != 1 || toolItems[0].Key != "doctor" || toolItems[0].Kind != "tool" {
		t.Fatalf("tool filter mismatch: %#v", toolItems)
	}

	advancedItems := filterMenuItems(items, "advanced:direct")
	if len(advancedItems) != 1 || advancedItems[0].Key != "advanced.direct_flow" || advancedItems[0].Kind != "advanced" {
		t.Fatalf("advanced filter mismatch: %#v", advancedItems)
	}
}

func TestModeOutlineLocalized(t *testing.T) {
	en := modeStageLines("en", "spec_flow")
	zh := modeStageLines("zh", "spec_flow")
	if len(en) == 0 || len(zh) == 0 {
		t.Fatalf("missing outline lines")
	}
	if en[1] == zh[1] {
		t.Fatalf("expected localized outline labels, got %q", en[1])
	}
}

func TestRequestManifestPayloadAndCommand(t *testing.T) {
	form := buildRequestForm("en", "spec_flow")
	if form == nil {
		t.Fatalf("expected spec_flow form")
	}
	form.Values["spec_source"] = "specs/inbox/spec.md"
	payload := createRequestManifestPayload(form, "tui_logic_spec", true, runtimeState{Model: "m1", Variant: "v1"})
	if payload["mode"] != "spec_flow" {
		t.Fatalf("unexpected mode: %#v", payload["mode"])
	}
	execMap, _ := payload["execution"].(map[string]any)
	if execMap["mode"] != "plan" {
		t.Fatalf("unexpected execution mode: %#v", execMap["mode"])
	}
	inputs, _ := payload["inputs"].(map[string]any)
	specSource, _ := inputs["spec_source"].(map[string]any)
	if specSource["import_mode"] != "snapshot" {
		t.Fatalf("unexpected import_mode: %#v", specSource["import_mode"])
	}

	cmd := buildRequestRunnerArgs("scripts/runner.py", "/tmp/request.form.json", runtimeState{Model: "m1", Variant: "v1"})
	wantTail := []string{"request", "--request-manifest", "/tmp/request.form.json", "--model", "m1", "--variant", "v1"}
	if len(cmd) < len(wantTail)+1 {
		t.Fatalf("request command too short: %#v", cmd)
	}
	gotTail := cmd[len(cmd)-len(wantTail):]
	for i := range wantTail {
		if gotTail[i] != wantTail[i] {
			t.Fatalf("request command mismatch: got %#v want %#v", gotTail, wantTail)
		}
	}
}

func TestCompletePathInput(t *testing.T) {
	projectRoot := filepath.Clean(filepath.Join("..", ".."))
	completed, message := completePathInput(projectRoot, "cocotb_ex/ai_cli_pipeline/examples/incremental_manifestless/sp", "en")
	want := "cocotb_ex/ai_cli_pipeline/examples/incremental_manifestless/spec.md"
	if filepath.ToSlash(completed) != want {
		t.Fatalf("unexpected completed path: got %q want %q", filepath.ToSlash(completed), want)
	}
	if !strings.Contains(strings.ToLower(message), "completed") {
		t.Fatalf("unexpected completion message: %q", message)
	}
}

func TestCompletePathInputDetailedReturnsCandidateList(t *testing.T) {
	projectRoot := filepath.Clean(filepath.Join("..", ".."))
	updated, message, candidates, baseDir := completePathInputDetailed(projectRoot, "cocotb_ex/ai_cli_pipeline/examples/incremental_manifestless/", "en")
	if updated != "" {
		t.Fatalf("expected no single updated value when multiple matches exist, got %q", updated)
	}
	if baseDir == "" || !strings.Contains(filepath.ToSlash(baseDir), "incremental_manifestless") {
		t.Fatalf("unexpected completion base dir: %q", baseDir)
	}
	if len(candidates) < 4 {
		t.Fatalf("expected multiple completion candidates, got %#v", candidates)
	}
	if !strings.Contains(strings.ToLower(message), "matches") {
		t.Fatalf("unexpected completion message: %q", message)
	}
}

func TestSliceVisibleLinesWithScroll(t *testing.T) {
	lines := []string{
		"line-0", "line-1", "line-2", "line-3", "line-4",
		"line-5", "line-6", "line-7", "line-8", "line-9",
	}
	got, effectiveScroll, maxScroll := sliceVisibleLines(lines, 4, 3)
	want := []string{"line-3", "line-4", "line-5", "line-6"}
	if effectiveScroll != 3 || maxScroll != 6 {
		t.Fatalf("unexpected scroll bounds: effective=%d max=%d", effectiveScroll, maxScroll)
	}
	if len(got) != len(want) {
		t.Fatalf("unexpected line count: got=%d want=%d", len(got), len(want))
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("unexpected visible line at %d: got=%q want=%q", i, got[i], want[i])
		}
	}
}

func TestRenderHelpOverlayWrapsWithoutEllipsis(t *testing.T) {
	m := model{locale: "en"}
	got := m.renderHelpOverlay(12)
	normalized := strings.ReplaceAll(strings.ReplaceAll(got, "\n", ""), " ", "")
	if strings.Contains(got, "…") {
		t.Fatalf("expected wrapped help overlay without ellipsis, got %q", got)
	}
	if !strings.Contains(normalized, "Shift+Up/Downscrolloutput") {
		t.Fatalf("expected full help content to survive wrapping, got %q", got)
	}
}

func TestRenderRightPanelWrapsResultPathsWithoutEllipsis(t *testing.T) {
	m := model{
		locale:  "en",
		logView: "RESULTS",
		resultManifest: map[string]any{
			"mode":   "spec_flow",
			"rc":     0,
			"run_id": "run_test",
			"primary_artifacts": []any{
				map[string]any{
					"label":  "verify_report",
					"path":   "/tmp/very/long/path/to/verify/report.md",
					"exists": true,
				},
			},
		},
	}
	got := renderRightPanel(m, 24, 12)
	normalized := strings.ReplaceAll(got, "\n", "")
	if strings.Contains(got, "…") {
		t.Fatalf("expected wrapped result panel without ellipsis, got %q", got)
	}
	if !strings.Contains(normalized, "/tmp/very/long/path/to/verify/report.md") {
		t.Fatalf("expected full result path in rendered panel, got %q", got)
	}
}

func TestBuildResultLinesRequirementsView(t *testing.T) {
	projectRoot, err := filepath.Abs(filepath.Clean(filepath.Join("..", "..")))
	if err != nil {
		t.Fatalf("abs project root: %v", err)
	}
	promptPath := filepath.Join(projectRoot, "artifacts", "tests", "tmp_requirements_prompt.txt")
	if err := os.MkdirAll(filepath.Dir(promptPath), 0o755); err != nil {
		t.Fatalf("mkdir prompt dir: %v", err)
	}
	defer os.Remove(promptPath)
	if err := os.WriteFile(promptPath, []byte("requirements prompt body\nsecond line\n"), 0o644); err != nil {
		t.Fatalf("write prompt file: %v", err)
	}

	manifest := map[string]any{
		"mode": "handoff_intake",
		"primary_artifacts": []any{
			map[string]any{
				"id":           "handoff_requirements_prompt",
				"label":        "handoff_requirements_prompt",
				"abs_path":     filepath.ToSlash(promptPath),
				"exists":       true,
				"preview_only": true,
			},
		},
	}
	lines := buildResultLines("en", manifest, "REQUIREMENTS", nil, "handoff_intake", nil)
	got := strings.Join(lines, "\n")
	if !strings.Contains(got, "handoff_requirements_prompt") {
		t.Fatalf("missing prompt label in prompt view: %q", got)
	}
	if !strings.Contains(got, "requirements prompt body") {
		t.Fatalf("missing prompt body in prompt view: %q", got)
	}
}

func TestBuildResultLinesBasisViewShowsSourceRequirements(t *testing.T) {
	projectRoot, err := filepath.Abs(filepath.Clean(filepath.Join("..", "..")))
	if err != nil {
		t.Fatalf("abs project root: %v", err)
	}
	sourceDir := filepath.Join(projectRoot, "artifacts", "tests", "tmp_source_requirements")
	if err := os.MkdirAll(sourceDir, 0o755); err != nil {
		t.Fatalf("mkdir source requirements dir: %v", err)
	}
	defer os.RemoveAll(sourceDir)
	if err := os.WriteFile(filepath.Join(sourceDir, "spec.md"), []byte("spec source\n"), 0o644); err != nil {
		t.Fatalf("write spec source: %v", err)
	}

	manifest := map[string]any{
		"mode":             "handoff_intake",
		"request_manifest": "/tmp/request.json",
		"input_artifacts": []any{
			map[string]any{
				"name":          "source_requirements_root",
				"resolved_path": filepath.ToSlash(sourceDir),
				"original_path": filepath.ToSlash(sourceDir),
			},
		},
	}
	lines := buildResultLines("en", manifest, "BASIS", nil, "handoff_intake", nil)
	got := strings.Join(lines, "\n")
	if !strings.Contains(got, "Source Requirements") {
		t.Fatalf("missing source requirements section in basis view: %q", got)
	}
	if !strings.Contains(got, "spec.md") {
		t.Fatalf("missing source requirements file list in basis view: %q", got)
	}
}

func TestBuildHandoffFeedbackLinesPrioritizesSemanticRepair(t *testing.T) {
	lines := buildHandoffFeedbackLines("en", nil, []promptEntry{
		{ID: "handoff_contract_repair_prompt", Label: "handoff_contract_repair_prompt.txt", Content: "contract prompt"},
		{ID: "handoff_semantic_repair_prompt", Label: "handoff_semantic_repair_prompt.txt", Content: "semantic prompt"},
	})
	got := strings.Join(lines, "\n")
	firstSemantic := strings.Index(got, "handoff_semantic_repair_prompt.txt")
	firstContract := strings.Index(got, "handoff_contract_repair_prompt.txt")
	if firstSemantic == -1 || firstContract == -1 {
		t.Fatalf("missing prompt labels in feedback view: %q", got)
	}
	if firstSemantic > firstContract {
		t.Fatalf("expected semantic repair prompt to be shown before contract repair prompt: %q", got)
	}
}

func TestRecommendedResultViewForManifestUsesFeedbackOnNeedsRepair(t *testing.T) {
	projectRoot, err := filepath.Abs(filepath.Clean(filepath.Join("..", "..")))
	if err != nil {
		t.Fatalf("abs project root: %v", err)
	}
	acceptancePath := filepath.Join(projectRoot, "artifacts", "tests", "tmp_handoff_acceptance.json")
	semanticPromptPath := filepath.Join(projectRoot, "artifacts", "tests", "tmp_handoff_semantic_repair_prompt.txt")
	if err := os.MkdirAll(filepath.Dir(acceptancePath), 0o755); err != nil {
		t.Fatalf("mkdir acceptance dir: %v", err)
	}
	defer os.Remove(acceptancePath)
	defer os.Remove(semanticPromptPath)
	if err := os.WriteFile(acceptancePath, []byte("{\"status\":\"needs_repair\",\"semantic_status\":\"needs_repair\"}\n"), 0o644); err != nil {
		t.Fatalf("write acceptance: %v", err)
	}
	if err := os.WriteFile(semanticPromptPath, []byte("repair me\n"), 0o644); err != nil {
		t.Fatalf("write semantic prompt: %v", err)
	}
	manifest := map[string]any{
		"mode": "handoff_intake",
		"primary_artifacts": []any{
			map[string]any{
				"id":       "handoff_acceptance",
				"abs_path": filepath.ToSlash(acceptancePath),
				"exists":   true,
			},
			map[string]any{
				"id":       "handoff_semantic_repair_prompt",
				"abs_path": filepath.ToSlash(semanticPromptPath),
				"exists":   true,
			},
		},
	}
	if got := recommendedResultViewForManifest(manifest); got != "FEEDBACK" {
		t.Fatalf("unexpected recommended view: got %q want %q", got, "FEEDBACK")
	}
}

func TestSessionIDHintForFormUsesExistingSessionPath(t *testing.T) {
	projectRoot, err := filepath.Abs(filepath.Clean(filepath.Join("..", "..")))
	if err != nil {
		t.Fatalf("abs project root: %v", err)
	}
	form := &requestFormState{
		Mode: "incremental_verify_ready",
		Values: map[string]string{
			"handoff_manifest": filepath.Join(projectRoot, "cocotb_ex", "artifacts", "sessions", "example_sid", "handoff", "handoff_manifest.materialized.json"),
		},
	}
	got := sessionIDHintForForm(projectRoot, form)
	if got != "example_sid" {
		t.Fatalf("unexpected session id hint: got %q want %q", got, "example_sid")
	}
}

func TestHelpOverlayOpensWhileRunning(t *testing.T) {
	m := model{
		locale:            "en",
		running:           true,
		confirmRunnerArgs: []string{"scripts/runner.py", "run", "all"},
	}
	updatedModel, cmd := m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'?'}})
	if cmd != nil {
		t.Fatalf("expected no command when opening help, got %v", cmd)
	}
	updated, ok := updatedModel.(model)
	if !ok {
		t.Fatalf("unexpected updated model type: %T", updatedModel)
	}
	if updated.overlayMode != "help" {
		t.Fatalf("expected help overlay while running, got %q", updated.overlayMode)
	}
	if len(updated.confirmRunnerArgs) != 0 {
		t.Fatalf("expected help overlay to clear confirm state, got %#v", updated.confirmRunnerArgs)
	}
	if updated.status != "Help overlay open" {
		t.Fatalf("unexpected status: %q", updated.status)
	}
}

func TestArmQuitThreePresses(t *testing.T) {
	m := model{locale: "en"}
	var cmd any
	m, _ = m.armQuit()
	if m.quitPresses != 1 {
		t.Fatalf("expected first quit press to arm, got %d", m.quitPresses)
	}
	m, _ = m.armQuit()
	if m.quitPresses != 2 {
		t.Fatalf("expected second quit press to arm, got %d", m.quitPresses)
	}
	m, cmd = m.armQuit()
	if cmd == nil {
		t.Fatalf("expected third quit press to return quit cmd")
	}
	if m.quitPresses != 0 {
		t.Fatalf("expected quit state reset after exit, got %d", m.quitPresses)
	}
}
