#!/usr/bin/env node

/**
 * AI Evals Framework — Interactive Plugin Installer
 *
 * Detects runtime (Claude Code, Cursor), creates directory structure,
 * copies skills/commands/hooks to the appropriate location.
 */

const fs = require("fs");
const path = require("path");
const readline = require("readline");
const os = require("os");

const VERSION = "1.0.0";

// ANSI color codes
const BOLD = "\x1b[1m";
const DIM = "\x1b[2m";
const GREEN = "\x1b[32m";
const CYAN = "\x1b[36m";
const YELLOW = "\x1b[33m";
const RED = "\x1b[31m";
const RESET = "\x1b[0m";

const SKILLS = [
  { name: "eval-runner", desc: "Run evaluations on AI outputs and pipelines" },
  { name: "eval-reporter", desc: "Generate quality reports and dashboards" },
  { name: "eval-judge", desc: "LLM-as-judge rubric evaluation" },
  { name: "eval-feedback", desc: "Capture quality feedback on AI outputs" },
];

const COMMANDS = [
  { name: "eval:report", desc: "Generate daily/weekly/trend reports" },
  { name: "eval:regression", desc: "Detect and investigate quality regressions" },
];

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function ask(question) {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });
  return new Promise((resolve) => {
    rl.question(question, (answer) => {
      rl.close();
      resolve(answer.trim());
    });
  });
}

function copyDirRecursive(src, dest) {
  if (!fs.existsSync(dest)) fs.mkdirSync(dest, { recursive: true });

  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      copyDirRecursive(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

function getPluginRoot() {
  let dir = __dirname;
  while (dir !== path.dirname(dir)) {
    if (
      fs.existsSync(path.join(dir, "skills")) &&
      fs.existsSync(path.join(dir, ".claude-plugin"))
    ) {
      return dir;
    }
    dir = path.dirname(dir);
  }
  return path.resolve(__dirname, "..");
}

function detectRuntimes() {
  const found = [];
  if (fs.existsSync(path.join(os.homedir(), ".claude"))) found.push("claude");
  if (fs.existsSync(path.join(os.homedir(), ".cursor"))) found.push("cursor");
  return found;
}

// ---------------------------------------------------------------------------
// Banner & display
// ---------------------------------------------------------------------------

function printBanner() {
  console.log();
  console.log(`${BOLD}${CYAN}  AI Evals Framework ${DIM}v${VERSION}${RESET}`);
  console.log(
    `${DIM}  Continuous evaluation for AI agent ecosystems${RESET}`
  );
  console.log();
}

function printSkillsTable() {
  console.log(`${BOLD}  Skills (${SKILLS.length}):${RESET}`);
  for (const s of SKILLS) {
    console.log(
      `    ${GREEN}/eval:${s.name}${RESET}  ${DIM}${s.desc}${RESET}`
    );
  }
  console.log();
  console.log(`${BOLD}  Commands (${COMMANDS.length}):${RESET}`);
  for (const c of COMMANDS) {
    console.log(`    ${GREEN}/${c.name}${RESET}  ${DIM}${c.desc}${RESET}`);
  }
  console.log();
}

// ---------------------------------------------------------------------------
// Data directory setup
// ---------------------------------------------------------------------------

function ensureDataDirs() {
  const base = path.join(os.homedir(), ".ai-evals");
  const dirs = ["results", "golden", "feedback", "reports", "rubrics"];

  for (const dir of dirs) {
    const dirPath = path.join(base, dir);
    if (!fs.existsSync(dirPath)) {
      fs.mkdirSync(dirPath, { recursive: true });
    }
  }

  // Write default config if none exists
  const configPath = path.join(base, "config.yaml");
  if (!fs.existsSync(configPath)) {
    const defaultConfig = [
      "# AI Evals Framework Configuration",
      "version: 1",
      "",
      "# LLM judge model (used for Tier 2 evaluations)",
      "judge_model: claude-sonnet-4-6",
      "",
      "# Data directories",
      "results_dir: ~/.ai-evals/results",
      "golden_dir: ~/.ai-evals/golden",
      "feedback_dir: ~/.ai-evals/feedback",
      "reports_dir: ~/.ai-evals/reports",
      "",
      "# Thresholds",
      "thresholds:",
      "  regression_pct: 15",
      "  golden_staleness_days: 30",
      "  pipeline_row_deviation_pct: 20",
      "",
      "# Category scoring weights (must sum to ~1.0)",
      "scoring_weights:",
      "  structured_docs: 0.20",
      "  reasoning: 0.15",
      "  data_analytics: 0.15",
      "  code_technical: 0.15",
      "  search_retrieval: 0.10",
      "  pipelines: 0.10",
      "  mcp_reliability: 0.15",
    ].join("\n");

    fs.writeFileSync(configPath, defaultConfig + "\n");
  }

  return base;
}

// ---------------------------------------------------------------------------
// Installation functions
// ---------------------------------------------------------------------------

function installClaude(pluginRoot, scope) {
  const base =
    scope === "global"
      ? path.join(os.homedir(), ".claude")
      : path.join(process.cwd(), ".claude");

  const skillsDest = path.join(base, "skills");
  const commandsDest = path.join(base, "commands", "eval");

  fs.mkdirSync(skillsDest, { recursive: true });
  fs.mkdirSync(commandsDest, { recursive: true });

  // Copy skills
  const skillsSrc = path.join(pluginRoot, "skills");
  let skillCount = 0;
  if (fs.existsSync(skillsSrc)) {
    for (const skill of fs.readdirSync(skillsSrc, { withFileTypes: true })) {
      if (skill.isDirectory()) {
        copyDirRecursive(
          path.join(skillsSrc, skill.name),
          path.join(skillsDest, skill.name)
        );
        skillCount++;
      }
    }
  }

  // Copy commands
  const commandsSrc = path.join(pluginRoot, "commands", "eval");
  let cmdCount = 0;
  if (fs.existsSync(commandsSrc)) {
    for (const cmd of fs.readdirSync(commandsSrc)) {
      fs.copyFileSync(
        path.join(commandsSrc, cmd),
        path.join(commandsDest, cmd)
      );
      cmdCount++;
    }
  }

  // Merge hooks (don't overwrite existing)
  const hooksSrc = path.join(pluginRoot, "hooks", "hooks.json");
  let hookCount = 0;
  if (fs.existsSync(hooksSrc)) {
    const hooksDest = path.join(base, "hooks");
    fs.mkdirSync(hooksDest, { recursive: true });

    // Copy hook scripts
    const hooksScriptsSrc = path.join(pluginRoot, "hooks");
    for (const f of fs.readdirSync(hooksScriptsSrc)) {
      if (f === "hooks.json") continue;
      fs.copyFileSync(
        path.join(hooksScriptsSrc, f),
        path.join(hooksDest, f)
      );
    }

    // Merge hooks.json
    const newHooks = JSON.parse(fs.readFileSync(hooksSrc, "utf-8"));
    const existingPath = path.join(hooksDest, "hooks.json");
    let merged;

    if (fs.existsSync(existingPath)) {
      const existing = JSON.parse(fs.readFileSync(existingPath, "utf-8"));
      const existingCommands = new Set(
        (existing.hooks || []).map((h) => h.command)
      );
      const toAdd = (newHooks.hooks || []).filter(
        (h) => !existingCommands.has(h.command)
      );
      merged = {
        hooks: [...(existing.hooks || []), ...toAdd],
      };
      hookCount = toAdd.length;
    } else {
      merged = newHooks;
      hookCount = (newHooks.hooks || []).length;
    }

    fs.writeFileSync(
      existingPath,
      JSON.stringify(merged, null, 2) + "\n"
    );
  }

  return { base, skillCount, cmdCount, hookCount };
}

function installCursor(pluginRoot, scope) {
  const base =
    scope === "global"
      ? path.join(os.homedir(), ".cursor", "skills")
      : path.join(process.cwd(), ".cursor", "skills");

  fs.mkdirSync(base, { recursive: true });

  const skillsSrc = path.join(pluginRoot, "skills");
  let skillCount = 0;
  if (fs.existsSync(skillsSrc)) {
    for (const skill of fs.readdirSync(skillsSrc, { withFileTypes: true })) {
      if (skill.isDirectory()) {
        copyDirRecursive(
          path.join(skillsSrc, skill.name),
          path.join(base, skill.name)
        );
        skillCount++;
      }
    }
  }

  return { base, skillCount };
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  printBanner();

  const pluginRoot = getPluginRoot();

  if (!fs.existsSync(path.join(pluginRoot, "skills"))) {
    console.error(
      `${RED}Error: Could not find plugin skills directory.${RESET}`
    );
    console.error(`Expected at: ${pluginRoot}/skills/`);
    process.exit(1);
  }

  // Detect runtimes
  const detected = detectRuntimes();
  console.log(
    `${DIM}  Detected: ${detected.length > 0 ? detected.join(", ") : "none"}${RESET}`
  );
  console.log();

  printSkillsTable();

  // Choose runtime
  console.log(`  ${BOLD}Choose runtime:${RESET}`);
  console.log(`    ${CYAN}1${RESET}) Claude Code`);
  console.log(`    ${CYAN}2${RESET}) Cursor`);
  console.log(`    ${CYAN}3${RESET}) Both`);
  console.log();

  const runtimeChoice = await ask(`  ${BOLD}Runtime [1-3]:${RESET} `);
  let runtimes = [];
  switch (runtimeChoice) {
    case "2":
      runtimes = ["cursor"];
      break;
    case "3":
      runtimes = ["claude", "cursor"];
      break;
    default:
      runtimes = ["claude"];
  }

  // Choose scope
  console.log();
  console.log(`  ${BOLD}Choose scope:${RESET}`);
  console.log(
    `    ${CYAN}1${RESET}) Global (all projects -- recommended)`
  );
  console.log(`    ${CYAN}2${RESET}) Local (current project only)`);
  console.log();

  const scopeChoice = await ask(`  ${BOLD}Scope [1-2]:${RESET} `);
  const scope = scopeChoice === "2" ? "local" : "global";

  // Create data directories
  console.log();
  console.log(`${BOLD}  Installing...${RESET}`);
  console.log();

  const dataDir = ensureDataDirs();
  console.log(`  ${GREEN}+${RESET} Data directory -- ${DIM}${dataDir}${RESET}`);

  // Install to each runtime
  for (const runtime of runtimes) {
    if (runtime === "claude") {
      const result = installClaude(pluginRoot, scope);
      console.log(
        `  ${GREEN}+${RESET} Claude Code -- ${DIM}${result.base}${RESET}`
      );
      console.log(
        `    ${DIM}Skills: ${result.skillCount} | Commands: ${result.cmdCount} | Hooks: ${result.hookCount}${RESET}`
      );
    } else if (runtime === "cursor") {
      const result = installCursor(pluginRoot, scope);
      console.log(
        `  ${GREEN}+${RESET} Cursor -- ${DIM}${result.base}${RESET}`
      );
      console.log(
        `    ${DIM}Skills: ${result.skillCount} (commands and hooks require Claude Code)${RESET}`
      );
    }
  }

  // Summary
  console.log();
  console.log(
    `  ${GREEN}${BOLD}Done!${RESET} Restart your editor to load the eval skills.`
  );
  console.log();

  if (runtimes.includes("claude")) {
    console.log(
      `  ${BOLD}Quick start:${RESET}`
    );
    console.log(
      `    ${CYAN}/eval:report${RESET}      -- generate today's quality report`
    );
    console.log(
      `    ${CYAN}/eval:regression${RESET}  -- check for quality regressions`
    );
  }

  // Check dependencies
  const deps = [
    {
      cmd: "python3",
      label: "python3",
      why: "eval engine and reports",
      fix: "brew install python3",
    },
  ];

  const missing = [];
  for (const dep of deps) {
    try {
      require("child_process").execSync(`which ${dep.cmd}`, {
        stdio: "ignore",
      });
    } catch {
      missing.push(dep);
    }
  }

  if (missing.length > 0) {
    console.log();
    console.log(`  ${YELLOW}Missing dependencies:${RESET}`);
    for (const dep of missing) {
      console.log(
        `    ${YELLOW}!${RESET} ${dep.label} -- ${dep.why} (${DIM}${dep.fix}${RESET})`
      );
    }
  }

  console.log();
  console.log(
    `  ${DIM}Docs: https://github.com/ahmedkhaledmohamed/ai-evals-framework${RESET}`
  );
  console.log();
}

main().catch((err) => {
  console.error(`${RED}Error: ${err.message}${RESET}`);
  process.exit(1);
});
