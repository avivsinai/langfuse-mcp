.PHONY: check-skills release release-skills

# Skill integrity: skills/ is canonical, .claude/skills/ and .agents/skills/ are symlinks
check-skills:
	@echo "Checking skill symlinks..."
	@test -L .claude/skills/langfuse || (echo "❌ .claude/skills/langfuse is not a symlink" && exit 1)
	@test -L .agents/skills/langfuse || (echo "❌ .agents/skills/langfuse is not a symlink" && exit 1)
	@test "$$(readlink .claude/skills/langfuse)" = "../../skills/langfuse" || (echo "❌ .claude/skills/langfuse target is not ../../skills/langfuse" && exit 1)
	@test "$$(readlink .agents/skills/langfuse)" = "../../skills/langfuse" || (echo "❌ .agents/skills/langfuse target is not ../../skills/langfuse" && exit 1)
	@diff -rq skills/langfuse .claude/skills/langfuse || (echo "❌ .claude/skills/langfuse content mismatch" && exit 1)
	@echo "✓ Skill symlinks valid"

release:
	@test -n "$(RELEASE_VERSION)" || (echo "usage: make release RELEASE_VERSION=X.Y.Z [RELEASE_DATE=YYYY-MM-DD] [RELEASE_ALLOW_EMPTY=1] [RELEASE_SKIP_VERIFY=1] [RELEASE_NO_AUTO_MERGE=1]" && exit 1)
	./scripts/release.sh "$(RELEASE_VERSION)" $(if $(RELEASE_DATE),--date $(RELEASE_DATE),) $(if $(RELEASE_ALLOW_EMPTY),--allow-empty,) $(if $(RELEASE_SKIP_VERIFY),--skip-verify,) $(if $(RELEASE_NO_AUTO_MERGE),--no-auto-merge,)

release-skills:
	@echo "warning: make release-skills is deprecated; use make release instead" >&2
	$(MAKE) release RELEASE_VERSION="$(RELEASE_VERSION)" RELEASE_DATE="$(RELEASE_DATE)" RELEASE_ALLOW_EMPTY="$(RELEASE_ALLOW_EMPTY)" RELEASE_SKIP_VERIFY="$(RELEASE_SKIP_VERIFY)" RELEASE_NO_AUTO_MERGE="$(RELEASE_NO_AUTO_MERGE)"
