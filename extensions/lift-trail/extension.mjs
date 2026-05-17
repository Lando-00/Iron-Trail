// Extension: lift-trail
//
// Registers /lift-review (weekly) and /lift-review-monthly slash commands
// in the Copilot CLI. Both shell out to the IronTrail repo's Python
// scripts/lift_review.py and report the path of the written note.
//
// Args supported on /lift-review:
//   /lift-review                           — weekly review, current personality
//   /lift-review --monthly                 — monthly recap
//   /lift-review --personality goggins     — pick a personality
//   /lift-review --vault <path>            — override the vault dir
//
// Configuration via environment variables (set in your shell profile):
//   IRON_TRAIL_REPO   — path to the iron-trail repo (default: D:/Dev/iron-trail)
//   IRON_TRAIL_VAULT  — default vault directory (fallback: <repo>/vault-output)
//   IRON_TRAIL_VENV   — venv path (default: <repo>/.venv on Win, <repo>/.venv on *nix)
//
// The extension stays thin (~150 LoC). All heavy lifting lives in Python.

import { existsSync } from "node:fs";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { joinSession } from "@github/copilot-sdk/extension";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const IRON_TRAIL_REPO =
    process.env.IRON_TRAIL_REPO ||
    (process.platform === "win32" ? "D:/Dev/iron-trail" : `${process.env.HOME}/iron-trail`);

const IRON_TRAIL_VAULT =
    process.env.IRON_TRAIL_VAULT || join(IRON_TRAIL_REPO, "vault-output");

const IRON_TRAIL_VENV =
    process.env.IRON_TRAIL_VENV || join(IRON_TRAIL_REPO, ".venv");

const isWindows = process.platform === "win32";

const PYTHON = isWindows
    ? join(IRON_TRAIL_VENV, "Scripts", "python.exe")
    : join(IRON_TRAIL_VENV, "bin", "python");

const LIFT_REVIEW_SCRIPT = join(IRON_TRAIL_REPO, "scripts", "lift_review.py");

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function parseArgs(argString) {
    // Lightweight tokenizer — splits on whitespace, respects "quoted strings".
    const args = [];
    let buf = "";
    let inQuotes = false;
    for (const ch of argString || "") {
        if (ch === '"' || ch === "'") {
            inQuotes = !inQuotes;
            continue;
        }
        if (/\s/.test(ch) && !inQuotes) {
            if (buf) {
                args.push(buf);
                buf = "";
            }
        } else {
            buf += ch;
        }
    }
    if (buf) args.push(buf);
    return args;
}

function takeOption(args, name) {
    const idx = args.indexOf(name);
    if (idx === -1) return null;
    const value = args[idx + 1];
    args.splice(idx, 2);
    return value;
}

function runLiftReview(session, scriptArgs) {
    return new Promise((resolve, reject) => {
        if (!existsSync(PYTHON)) {
            return reject(
                new Error(
                    `Python venv not found at ${PYTHON}. ` +
                        `Set IRON_TRAIL_REPO or IRON_TRAIL_VENV.`,
                ),
            );
        }
        if (!existsSync(LIFT_REVIEW_SCRIPT)) {
            return reject(
                new Error(
                    `Script not found at ${LIFT_REVIEW_SCRIPT}. ` +
                        `Set IRON_TRAIL_REPO to the iron-trail repo root.`,
                ),
            );
        }
        const child = spawn(PYTHON, [LIFT_REVIEW_SCRIPT, ...scriptArgs], {
            cwd: IRON_TRAIL_REPO,
            env: {
                ...process.env,
                PYTHONIOENCODING: "utf-8",
            },
            stdio: ["ignore", "pipe", "pipe"],
        });
        let stdout = "";
        let stderr = "";
        child.stdout.on("data", (chunk) => {
            const text = chunk.toString("utf-8");
            stdout += text;
            // Stream each progress line into the CLI timeline
            for (const line of text.split(/\r?\n/)) {
                if (line.trim().startsWith("[lift_review]")) {
                    session.log(line.trim(), { ephemeral: true });
                }
            }
        });
        child.stderr.on("data", (chunk) => {
            stderr += chunk.toString("utf-8");
        });
        child.on("close", (code) => {
            if (code === 0) {
                // Last non-empty line of stdout is the output path
                const lines = stdout.trim().split(/\r?\n/).filter(Boolean);
                const path = lines.length ? lines[lines.length - 1] : "";
                resolve(path);
            } else {
                reject(
                    new Error(
                        `lift_review.py exited with code ${code}.\n` +
                            `stderr:\n${stderr.slice(-1000)}`,
                    ),
                );
            }
        });
    });
}

async function handle(session, ctx, defaultMonthly) {
    const args = parseArgs(ctx.args);
    const monthly = defaultMonthly || args.includes("--monthly");
    if (monthly) {
        const idx = args.indexOf("--monthly");
        if (idx !== -1) args.splice(idx, 1);
    }
    const personality = takeOption(args, "--personality") || "default";
    const vault = takeOption(args, "--vault") || IRON_TRAIL_VAULT;
    const since = takeOption(args, "--since");

    const scriptArgs = ["--vault", vault, "--personality", personality];
    if (monthly) scriptArgs.push("--monthly");
    if (since) scriptArgs.push("--since", since);

    session.log(
        `Generating ${monthly ? "monthly recap" : "weekly review"} ` +
            `(personality: ${personality}, vault: ${vault})`,
    );

    try {
        const path = await runLiftReview(session, scriptArgs);
        session.log(`Review written → ${path}`);
    } catch (err) {
        session.log(`/lift-review failed: ${err.message}`, { level: "error" });
        throw err;
    }
}

// ---------------------------------------------------------------------------
// Register
// ---------------------------------------------------------------------------

const session = await joinSession({
    commands: [
        {
            name: "lift-review",
            description: "Generate an IronTrail weekly training review and write it to the vault.",
            handler: async (ctx) => handle(session, ctx, false),
        },
        {
            name: "lift-recap",
            description: "Generate an IronTrail monthly training recap and write it to the vault.",
            handler: async (ctx) => handle(session, ctx, true),
        },
    ],
});

session.log("lift-trail extension loaded. Try /lift-review or /lift-recap.", {
    ephemeral: true,
});
