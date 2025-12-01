# Token Usage Optimization Plan

**Branch:** `optimize/token-usage`
**Date:** 2025-11-29
**Status:** Planning Phase

## Executive Summary

NightShift currently uses excessive tokens due to loading all MCP servers and providing large context files to both planning and execution agents. This plan outlines three critical optimization strategies to reduce token costs by 80-95%.

---

## Problem Analysis

### Current Token Usage Breakdown

Based on codebase analysis:

1. **MCP Server Loading (~15,000-50,000+ tokens)**
   - Current behavior: All MCP servers from `~/.claude.json.with_mcp_servers` are loaded for BOTH planner and executor
   - The planner agent (task_planner.py:175-183) calls `claude -p` WITHOUT any MCP filtering
   - The executor agent (agent_manager.py:389-412) uses `--allowed-tools` but this only restricts USAGE, not LOADING
   - With ~12 MCP servers (gemini, openai, arxiv, word, claude, py2nb, code2prompt, google-calendar, mathematica, reminders, python-env, amazon, otter), tool definitions consume massive token budget
   - **Critical insight:** `--allowed-tools` flag does NOT prevent tools from being loaded into context - it only blocks their usage

2. **Context Files Provided to Planner (~5,400+ tokens)**
   - `claude-code-tools-reference.md`: ~1,623 words (~2,200 tokens)
   - `directory-map.md`: ~3,750 words (~5,000 tokens)
   - Total: **~7,200 tokens** just from reference files
   - This is provided to the planner for EVERY task submission

3. **System Prompts and Schemas**
   - Planning prompt (task_planner.py:80-146): ~900 words (~1,200 tokens)
   - JSON schema definitions: ~200 tokens
   - System prompt for executor: Variable, typically 200-500 tokens

### Estimated Current Token Costs Per Task

| Component | Tokens | Cost Impact |
|-----------|--------|-------------|
| MCP tools (all 12 servers loaded) | 15,000-50,000 | **CRITICAL** |
| Tools reference file | ~2,200 | High |
| Directory map file | ~5,000 | High |
| Planning prompt + schema | ~1,400 | Medium |
| Executor system prompt | ~500 | Low |
| **TOTAL OVERHEAD** | **~24,000-59,000** | **Unacceptable** |

**This overhead applies to EVERY task before any actual work begins.**

---

## Optimization Strategy

### Priority 1: Dynamic MCP Server Configuration (CRITICAL - Est. 85-95% token savings)

**Problem:**
- Planner agent loads ALL MCP servers (~15,000-50,000 tokens) despite needing NONE
- Executor agent loads ALL MCP servers even when task only needs 0-2 specific tools
- `--allowed-tools` restricts usage but NOT context loading

**Solution:**
Implement dynamic MCP configuration generation:

```python
# New file: nightshift/core/mcp_config_manager.py

class MCPConfigManager:
    """Generates minimal MCP configs based on tool requirements"""

    def __init__(self, base_config_path: str = "~/.claude.json.with_mcp_servers"):
        """Load the full MCP server registry"""
        self.full_config = self._load_full_config(base_config_path)

    def create_minimal_config(self, required_tools: List[str], output_path: str) -> str:
        """
        Create a minimal MCP config containing ONLY the servers needed for required_tools.

        Args:
            required_tools: List like ['mcp__arxiv__download', 'mcp__gemini__ask', 'Read', 'Write']
            output_path: Where to write the temporary config file

        Returns:
            Path to generated config file
        """
        # Extract MCP server names from tool names (e.g., 'mcp__arxiv__download' -> 'arxiv')
        needed_servers = self._extract_server_names(required_tools)

        # Build minimal config with only these servers
        minimal_config = {
            "mcpServers": {
                server: self.full_config["mcpServers"][server]
                for server in needed_servers
                if server in self.full_config["mcpServers"]
            }
        }

        # Write to temp file
        with open(output_path, 'w') as f:
            json.dump(minimal_config, f, indent=2)

        return output_path

    def get_planner_config(self) -> str:
        """
        Create EMPTY MCP config for planner agent (needs NO MCP tools).

        Returns:
            Path to empty config file
        """
        empty_config = {"mcpServers": {}}
        path = "/tmp/nightshift_planner_mcp_empty.json"
        with open(path, 'w') as f:
            json.dump(empty_config, f)
        return path
```

**Implementation Steps:**

1. Create `MCPConfigManager` class to parse full MCP registry
2. Update `TaskPlanner._build_command()` to use `--mcp-config` with EMPTY config:
   ```python
   cmd = [
       self.claude_bin, "-p", planning_prompt,
       "--output-format", "json",
       "--json-schema", json_schema,
       "--mcp-config", mcp_manager.get_planner_config()  # NEW: Empty MCP config
   ]
   ```

3. Update `AgentManager._build_command()` to generate minimal config:
   ```python
   # Generate minimal MCP config based on task's allowed_tools
   mcp_config_path = self.mcp_manager.create_minimal_config(
       required_tools=task.allowed_tools,
       output_path=f"/tmp/nightshift_mcp_{task.task_id}.json"
   )

   cmd_parts.append(f"--mcp-config {mcp_config_path}")
   cmd_parts.append(f"--allowed-tools {' '.join(task.allowed_tools)}")  # Keep for extra safety
   ```

4. Clean up temporary MCP configs after task execution

**Expected Impact:**
- Planner: Reduce from ~25,000-55,000 tokens → ~7,000-9,000 tokens (**80-85% reduction**)
- Executor (typical task): Reduce from ~20,000-50,000 tokens → ~2,000-5,000 tokens (**85-95% reduction**)
- Executor (no MCP task): Reduce from ~20,000-50,000 tokens → ~500-1,000 tokens (**95-98% reduction**)

---

### Priority 2: Hierarchical Planning with Cheaper Models (Est. 60-80% cost reduction for planning)

**Problem:**
- Every task submission uses expensive model (Sonnet/Opus) for planning
- Large context files (7,200 tokens) loaded even for simple tasks
- Many tasks don't need MCP tools or directory navigation

**Solution:**
Implement two-tier planning:

```python
class HierarchicalPlanner:
    """Two-tier planning: cheap pre-filter, then full planning if needed"""

    def plan_task(self, description: str) -> Dict[str, Any]:
        # TIER 1: Use Haiku with minimal context for pre-filtering
        needs_advanced_planning = self._quick_assessment(description)

        if not needs_advanced_planning:
            # Simple task - use heuristics
            return self._simple_plan(description)

        # TIER 2: Use Sonnet with full context for complex tasks
        return self._full_planning(description)

    def _quick_assessment(self, description: str) -> bool:
        """
        Use Haiku (cheap, fast) to determine if task needs:
        - MCP tools
        - Directory navigation
        - Complex planning

        Cost: ~500-1,000 tokens with Haiku (~$0.0001-0.0003)
        """
        prompt = f"""Analyze this task description and determine complexity level.

        Task: {description}

        Answer these yes/no questions:
        1. Needs external MCP tools (arxiv, gemini, openai, etc.)?
        2. Needs directory structure navigation?
        3. Requires multi-step planning?

        Respond with JSON: {{"needs_mcp": bool, "needs_dirs": bool, "complex": bool}}
        """

        # Call with Haiku, minimal context
        result = subprocess.run([
            "claude", "-p", prompt,
            "--model", "haiku",
            "--output-format", "json",
            "--mcp-config", "/tmp/empty_mcp.json",  # No MCP servers
            "--json-schema", schema
        ], capture_output=True, text=True)

        assessment = json.loads(result.stdout)
        return any(assessment.values())  # True if ANY complexity detected
```

**Implementation Steps:**

1. Add `--model` flag support to planner calls
2. Create `_quick_assessment()` using Haiku for pre-filtering
3. Create `_simple_plan()` that uses heuristics for basic tasks (Read, Write, Bash only)
4. Modify `_full_planning()` to only load needed context files:
   - If `needs_mcp=False`: Skip tools reference file (-2,200 tokens)
   - If `needs_dirs=False`: Skip directory map (-5,000 tokens)
5. Add configuration flags:
   - `NIGHTSHIFT_ENABLE_HIERARCHICAL_PLANNING` (default: true)
   - `NIGHTSHIFT_PLANNER_MODEL` (default: "sonnet")
   - `NIGHTSHIFT_QUICK_ASSESS_MODEL` (default: "haiku")

**Expected Impact:**
- Simple tasks (50-70% of workload): Use Haiku with 500-1,000 tokens (~$0.0003)
- Complex tasks (30-50% of workload): Use Sonnet with 7,000-9,000 tokens (after Priority 1)
- Overall planning cost reduction: **60-80%**

---

### Priority 3: Model Selection for Execution (Est. 40-60% cost reduction for execution)

**Problem:**
- All tasks currently use default model (Sonnet 4 or Opus)
- Simple file operations, git commits, basic scripts don't need advanced reasoning
- Token costs compound: input context + output generation

**Solution:**
Model selection based on task complexity:

```python
class ModelSelector:
    """Select appropriate model based on task requirements"""

    # Model cost tiers (relative to Sonnet 4 = 1.0)
    MODEL_COSTS = {
        "haiku": 0.05,      # 5% of Sonnet cost
        "sonnet": 1.0,      # Baseline
        "opus": 3.0,        # 3x Sonnet cost
    }

    def select_execution_model(self, task: Task) -> str:
        """
        Determine optimal model for task execution.

        Decision tree:
        - Haiku: File operations, simple scripts, git commits, formatting
        - Sonnet: Data analysis, research tasks, multi-step workflows
        - Opus: Complex reasoning, architecture decisions, debugging
        """

        # Check task metadata from planner
        if task.estimated_tokens < 500:
            return "haiku"  # Very simple task

        # Check tool requirements
        simple_tools = {'Read', 'Write', 'Edit', 'Bash', 'Glob', 'Grep'}
        if set(task.allowed_tools).issubset(simple_tools):
            return "haiku"  # Only basic file operations

        # Check for research/analysis keywords
        research_keywords = ['arxiv', 'analyze', 'summarize', 'research', 'compare']
        if any(kw in task.description.lower() for kw in research_keywords):
            return "sonnet"  # Needs reasoning

        # Default to Sonnet for safety
        return "sonnet"
```

**Implementation Steps:**

1. Add `ModelSelector` class to determine execution model
2. Update `TaskPlanner.plan_task()` to include recommended model:
   ```python
   plan = {
       "enhanced_prompt": "...",
       "allowed_tools": [...],
       "recommended_model": "haiku",  # NEW FIELD
       "reasoning": "Simple file operation - Haiku sufficient"
   }
   ```

3. Update `AgentManager._build_command()` to use model selection:
   ```python
   if task.recommended_model:
       cmd_parts.append(f"--model {task.recommended_model}")
   ```

4. Add configuration overrides:
   - `NIGHTSHIFT_FORCE_MODEL` - Override all model selection
   - `NIGHTSHIFT_ENABLE_AUTO_MODEL_SELECTION` (default: true)

**Expected Impact:**
- File operations: Haiku instead of Sonnet (**95% cost reduction**)
- Simple automation: Haiku instead of Sonnet (**95% cost reduction**)
- Research tasks: Keep Sonnet (no change)
- Overall execution cost reduction: **40-60%** (assuming 50-70% of tasks can use Haiku)

---

## Implementation Roadmap

### Phase 1: MCP Config Management (Week 1)
- [ ] Create `MCPConfigManager` class
- [ ] Add empty MCP config for planner
- [ ] Implement dynamic MCP config generation for executor
- [ ] Add `--mcp-config` flags to both agents
- [ ] Test with sample tasks (arxiv, file operations, mixed)
- [ ] Verify token usage reduction via `--verbose` output

### Phase 2: Hierarchical Planning (Week 2)
- [ ] Implement `HierarchicalPlanner` class
- [ ] Add quick assessment using Haiku
- [ ] Create simple plan generator (heuristics)
- [ ] Modify full planning to load conditional context
- [ ] Add configuration flags
- [ ] Test planning accuracy vs. token cost tradeoff

### Phase 3: Model Selection (Week 3)
- [ ] Create `ModelSelector` class
- [ ] Update planner to recommend models
- [ ] Update executor to use recommended models
- [ ] Add configuration overrides
- [ ] Test execution quality across models
- [ ] Benchmark cost savings

### Phase 4: Validation & Documentation (Week 4)
- [ ] Integration testing with real workloads
- [ ] Token usage benchmarking (before/after)
- [ ] Cost analysis and reporting
- [ ] Update user documentation
- [ ] Add monitoring/logging for token usage

---

## Success Metrics

### Token Reduction Targets

| Metric | Before | After | Reduction |
|--------|--------|-------|-----------|
| **Planner overhead (simple task)** | 25,000-55,000 | 500-1,500 | **95-98%** |
| **Planner overhead (complex task)** | 25,000-55,000 | 7,000-10,000 | **80-85%** |
| **Executor overhead (no MCP)** | 20,000-50,000 | 500-1,000 | **95-98%** |
| **Executor overhead (1-2 MCP tools)** | 20,000-50,000 | 2,000-5,000 | **85-95%** |
| **Average cost per task** | $0.50-1.50 | $0.05-0.30 | **80-94%** |

### Quality Metrics (Must Maintain)
- Task success rate: >95% (current baseline)
- Planning accuracy: >90% tool selection correctness
- Execution quality: No degradation for Haiku-eligible tasks

---

## Risk Assessment

### High Risk
- **MCP config compatibility**: Claude CLI `--mcp-config` flag might have undocumented behavior
  - Mitigation: Test thoroughly with multiple MCP servers

- **Model quality degradation**: Haiku might not handle some tasks well
  - Mitigation: Conservative model selection, always allow Sonnet fallback

### Medium Risk
- **Hierarchical planning accuracy**: Quick assessment might misclassify tasks
  - Mitigation: Tune assessment prompts, log misclassifications, iterate

- **Temporary file cleanup**: MCP config files could accumulate
  - Mitigation: Cleanup in `finally` blocks, periodic /tmp cleanup

### Low Risk
- **Configuration complexity**: More knobs for users to tune
  - Mitigation: Sane defaults, clear documentation

---

## Configuration Options (Proposed)

```bash
# ~/.nightshift/config.yaml

# MCP Configuration
NIGHTSHIFT_BASE_MCP_CONFIG: "~/.claude.json.with_mcp_servers"
NIGHTSHIFT_ENABLE_DYNAMIC_MCP: true  # Priority 1

# Planning Configuration
NIGHTSHIFT_ENABLE_HIERARCHICAL_PLANNING: true  # Priority 2
NIGHTSHIFT_PLANNER_MODEL: "sonnet"
NIGHTSHIFT_QUICK_ASSESS_MODEL: "haiku"

# Execution Configuration
NIGHTSHIFT_ENABLE_AUTO_MODEL_SELECTION: true  # Priority 3
NIGHTSHIFT_FORCE_MODEL: null  # Override if set (e.g., "haiku", "sonnet", "opus")

# Debugging
NIGHTSHIFT_LOG_TOKEN_USAGE: true  # Log detailed token breakdowns
NIGHTSHIFT_MCP_CONFIG_DEBUG: false  # Keep temp MCP configs for inspection
```

---

## Next Steps

1. **Immediate**: Implement Priority 1 (Dynamic MCP Config) on this branch
2. **Week 1**: Test MCP config generation with various task types
3. **Week 2**: Add hierarchical planning if Priority 1 shows good results
4. **Week 3**: Add model selection optimization
5. **Week 4**: Production testing and cost analysis

---

## Token Usage Estimation Tool (To Build)

Create a utility to profile token usage:

```bash
# Proposed CLI command
nightshift profile-tokens "Download latest arxiv paper on transformers"

# Output:
# Token Usage Breakdown:
# - MCP servers loaded: 12 servers, ~35,000 tokens
# - Tools reference: ~2,200 tokens
# - Directory map: ~5,000 tokens
# - Planning prompt: ~1,400 tokens
# - TOTAL OVERHEAD: ~43,600 tokens
#
# With optimizations enabled:
# - MCP servers loaded: 1 server (arxiv), ~3,000 tokens
# - Tools reference: SKIPPED (not needed for quick assess)
# - Directory map: SKIPPED
# - Planning prompt: ~800 tokens (quick assess)
# - TOTAL OVERHEAD: ~3,800 tokens
#
# REDUCTION: 91.3% (-39,800 tokens)
# COST SAVINGS: ~$0.95 per task
```

---

## References

- Task planner: `nightshift/core/task_planner.py`
- Agent manager: `nightshift/core/agent_manager.py`
- Tools reference: `nightshift/config/claude-code-tools-reference.md` (1,623 words)
- Directory map: `nightshift/config/directory-map.md` (3,750 words)
- MCP registry: `~/.claude.json.with_mcp_servers`
- Claude CLI docs: https://docs.claude.com/en/docs/claude-code

---

**End of Plan**
