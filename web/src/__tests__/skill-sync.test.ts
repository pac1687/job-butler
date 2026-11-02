import {
  detectUnlistedSkillsFromBullets,
  guessSkillCategory,
  isSkillAlreadyPresent,
  normalizeSkillKey,
} from "../lib/skill-sync";

describe("Skill Sync Utility (Option 1: Experience Bullets -> Skills Sync)", () => {
  const currentSkills = {
    languages: ["TypeScript", "JavaScript (ES6+)", "Node.js"],
    frameworks: ["React", "NestJS"],
    cloud: ["AWS (Lambda, S3, SSM)", "Docker"],
    databases: ["PostgreSQL", "Redis"],
    ai_developer_tooling: [],
  };

  test("normalizeSkillKey strips parens, version notes, and whitespace", () => {
    expect(normalizeSkillKey("JavaScript (ES6+)")).toBe("javascript");
    expect(normalizeSkillKey("AWS (Lambda, S3)")).toBe("aws");
    expect(normalizeSkillKey("   Node.js   ")).toBe("node.js");
  });

  test("isSkillAlreadyPresent accurately flags existing technologies", () => {
    expect(isSkillAlreadyPresent("TypeScript", currentSkills)).toBe(true);
    expect(isSkillAlreadyPresent("React", currentSkills)).toBe(true);
    expect(isSkillAlreadyPresent("PostgreSQL", currentSkills)).toBe(true);
    // Unlisted skills
    expect(isSkillAlreadyPresent("AWS Kiro", currentSkills)).toBe(false);
    expect(isSkillAlreadyPresent("Claude", currentSkills)).toBe(false);
    expect(isSkillAlreadyPresent("Webpack", currentSkills)).toBe(false);
  });

  test("guessSkillCategory maps modern AI, cloud, and library tools to correct categories", () => {
    expect(guessSkillCategory("AWS Kiro")).toBe("ai_developer_tooling");
    expect(guessSkillCategory("Claude")).toBe("ai_developer_tooling");
    expect(guessSkillCategory("Webpack")).toBe("ai_developer_tooling");
    expect(guessSkillCategory("Kubernetes")).toBe("cloud");
    expect(guessSkillCategory("MongoDB")).toBe("databases");
    expect(guessSkillCategory("Python")).toBe("languages");
    expect(guessSkillCategory("Tailwind")).toBe("frameworks");
  });

  test("detectUnlistedSkillsFromBullets extracts AWS Kiro and Claude from Pushly bullet", () => {
    const bullets = [
      "Core Reliability & Systems Architecture: Maintained 13 repos, investigated hotfixes, and integrated developer tooling including AI tools and workflows (AWS Kiro using Claude models) to sustain platform reliability.",
      "Configured Webpack build tooling across existing and greenfield applications.",
      "Built APIs with Node and PostgreSQL.", // Already in currentSkills
    ];

    const detected = detectUnlistedSkillsFromBullets(bullets, currentSkills);
    const skillNames = detected.map((d) => d.skill);

    expect(skillNames).toContain("AWS Kiro");
    expect(skillNames).toContain("Claude");
    expect(skillNames).toContain("Webpack");
    // Should NOT contain Node or PostgreSQL because they are already present
    expect(skillNames).not.toContain("Node");
    expect(skillNames).not.toContain("PostgreSQL");

    const kiro = detected.find((d) => d.skill === "AWS Kiro");
    expect(kiro?.suggestedCategory).toBe("ai_developer_tooling");

    const claude = detected.find((d) => d.skill === "Claude");
    expect(claude?.suggestedCategory).toBe("ai_developer_tooling");
  });
});

