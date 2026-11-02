/**
 * Skill Sync Utility
 * Scans resume experience bullets for technologies/tools not yet present
 * in the candidate's master Technical Skills inventory.
 */

export interface DetectedSkillCandidate {
  skill: string;
  suggestedCategory: string;
  sourceBullet: string;
}

export const CATEGORY_LABELS: Record<string, string> = {
  languages: "Languages",
  frameworks: "Frameworks & Libraries",
  cloud: "Cloud & DevOps",
  databases: "Databases",
  ai_developer_tooling: "AI & Developer Tooling",
};

export const DEFAULT_CATEGORY_ORDER = [
  "languages",
  "frameworks",
  "cloud",
  "databases",
  "ai_developer_tooling",
];

const STOPWORDS = new Set([
  "and",
  "or",
  "using",
  "with",
  "to",
  "for",
  "across",
  "including",
  "models",
  "tools",
  "workflows",
  "mechanisms",
  "windows",
  "streams",
  "packages",
  "systems",
  "engine",
  "services",
  "platform",
  "architecture",
  "data",
  "apis",
  "api",
  "spas",
  "spa",
  "uis",
  "ui",
]);

/**
 * Standard categorized technical skill keywords for high-precision recognition.
 */
const KNOWN_TECH_MAP: Record<string, string> = {
  // AI & Developer Tooling
  "aws kiro": "ai_developer_tooling",
  kiro: "ai_developer_tooling",
  claude: "ai_developer_tooling",
  anthropic: "ai_developer_tooling",
  "openai / gpt": "ai_developer_tooling",
  chatgpt: "ai_developer_tooling",
  copilot: "ai_developer_tooling",
  langchain: "ai_developer_tooling",
  ollama: "ai_developer_tooling",
  webpack: "ai_developer_tooling",
  mocha: "ai_developer_tooling",
  chai: "ai_developer_tooling",
  rspec: "ai_developer_tooling",
  pgp: "ai_developer_tooling",
  bestcrypt: "ai_developer_tooling",
  jest: "ai_developer_tooling",

  // Cloud & DevOps
  aws: "cloud",
  "aws lambda": "cloud",
  lambda: "cloud",
  s3: "cloud",
  ssm: "cloud",
  "sns/sqs": "cloud",
  sns: "cloud",
  sqs: "cloud",
  docker: "cloud",
  serverless: "cloud",
  auth0: "cloud",
  "ci/cd": "cloud",
  kubernetes: "cloud",
  k8s: "cloud",
  terraform: "cloud",
  gcp: "cloud",
  azure: "cloud",

  // Languages
  javascript: "languages",
  typescript: "languages",
  "node.js": "languages",
  node: "languages",
  "ruby on rails": "languages",
  ruby: "languages",
  perl: "languages",
  sql: "languages",
  coffeescript: "languages",
  apex: "languages",
  python: "languages",
  csharp: "languages",
  "c#": "languages",
  ".net": "languages",
  ".net 6": "languages",
  go: "languages",
  rust: "languages",
  bash: "languages",

  // Frameworks & Libraries
  react: "frameworks",
  redux: "frameworks",
  nestjs: "frameworks",
  express: "frameworks",
  "material-ui": "frameworks",
  mui: "frameworks",
  highcharts: "frameworks",
  handsontable: "frameworks",
  "d3.js": "frameworks",
  d3: "frameworks",
  jquery: "frameworks",
  bootstrap: "frameworks",
  "angular 1.x": "frameworks",
  angular: "frameworks",
  "passport.js": "frameworks",
  knex: "frameworks",
  "next.js": "frameworks",
  vue: "frameworks",
  tailwind: "frameworks",
  fastapi: "frameworks",

  // Databases
  postgresql: "databases",
  postgres: "databases",
  mysql: "databases",
  redis: "databases",
  mongodb: "databases",
  sqlite: "databases",
  dynamodb: "databases",
  elasticsearch: "databases",
};

/**
 * Normalizes a skill string for fuzzy matching (stripping version numbers, parens, case).
 */
export function normalizeSkillKey(skill: string): string {
  return skill
    .toLowerCase()
    .replace(/\(.*?\)/g, "")
    .replace(/[^a-z0-9+#.-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Checks whether a candidate skill already exists in the candidate's skills dictionary.
 */
export function isSkillAlreadyPresent(
  candidate: string,
  skillsMap: Record<string, string[]>
): boolean {
  const normCandidate = normalizeSkillKey(candidate);
  if (!normCandidate || normCandidate.length < 2) return true;

  for (const list of Object.values(skillsMap)) {
    if (!Array.isArray(list)) continue;
    for (const existing of list) {
      const normExisting = normalizeSkillKey(existing);
      if (
        normCandidate === normExisting ||
        normCandidate.includes(normExisting) ||
        normExisting.includes(normCandidate)
      ) {
        return true;
      }
    }
  }
  return false;
}

/**
 * Guess the best matching skill category.
 */
export function guessSkillCategory(skill: string): string {
  const sLower = skill.toLowerCase().trim();
  if (KNOWN_TECH_MAP[sLower]) {
    return KNOWN_TECH_MAP[sLower];
  }

  for (const [known, cat] of Object.entries(KNOWN_TECH_MAP)) {
    if (sLower.includes(known) || known.includes(sLower)) {
      return cat;
    }
  }

  if (sLower.includes("ai") || sLower.includes("claude") || sLower.includes("gpt") || sLower.includes("model")) {
    return "ai_developer_tooling";
  }
  if (sLower.includes("cloud") || sLower.includes("aws") || sLower.includes("docker")) {
    return "cloud";
  }
  if (sLower.includes("sql") || sLower.includes("db") || sLower.includes("data")) {
    return "databases";
  }
  return "frameworks";
}

/**
 * Extracts candidate technologies from experience bullets and returns those not yet
 * present in the candidate's current Technical Skills map.
 */
export function detectUnlistedSkillsFromBullets(
  bullets: string[],
  currentSkills: Record<string, string[]>
): DetectedSkillCandidate[] {
  const candidates: Map<string, DetectedSkillCandidate> = new Map();

  for (const bullet of bullets) {
    if (!bullet || !bullet.trim()) continue;

    // 1. Extract terms inside parentheses: e.g. (CoffeeScript, Node), (AWS Kiro using Claude models)
    const parenMatches = bullet.match(/\(([^)]+)\)/g) || [];
    for (const match of parenMatches) {
      const inner = match.slice(1, -1);
      // Split on comma, slash, or semicolons
      const parts = inner.split(/[,;/]+/).map((p) => p.trim());
      for (let part of parts) {
        // Strip leading 'using' or 'and'
        part = part.replace(/^(using|and|with)\s+/i, "").trim();
        if (!part) continue;

        // If part has "using" or "models", clean it up
        // e.g. "AWS Kiro using Claude models" -> "AWS Kiro", "Claude"
        if (/using|models/i.test(part)) {
          const subparts = part
            .split(/\s+using\s+|\s+models\b/i)
            .map((s) => s.trim())
            .filter(Boolean);
          for (const sub of subparts) {
            recordCandidate(sub, bullet, currentSkills, candidates);
          }
        } else {
          recordCandidate(part, bullet, currentSkills, candidates);
        }
      }
    }

    // 2. Scan entire bullet for known high-value tech keywords
    for (const known of Object.keys(KNOWN_TECH_MAP)) {
      // Word boundary match
      const escaped = known.replace(/[-/\\^$*+?.()|[\]{}]/g, "\\$&");
      const regex = new RegExp(`(?<!\\w)${escaped}(?!\\w)`, "i");
      if (regex.test(bullet)) {
        // Capitalize nicely from standard mapping
        const properName = formatSkillName(known);
        recordCandidate(properName, bullet, currentSkills, candidates);
      }
    }
  }

  return Array.from(candidates.values());
}

function recordCandidate(
  skill: string,
  sourceBullet: string,
  currentSkills: Record<string, string[]>,
  candidateMap: Map<string, DetectedSkillCandidate>
) {
  const cleaned = skill
    .replace(/^[^a-zA-Z0-9.+]+|[^a-zA-Z0-9.+]+$/g, "")
    .trim();
  if (!cleaned || cleaned.length < 2) return;
  if (STOPWORDS.has(cleaned.toLowerCase())) return;

  if (isSkillAlreadyPresent(cleaned, currentSkills)) return;

  const key = cleaned.toLowerCase();
  if (!candidateMap.has(key)) {
    candidateMap.set(key, {
      skill: cleaned,
      suggestedCategory: guessSkillCategory(cleaned),
      sourceBullet,
    });
  }
}

function formatSkillName(raw: string): string {
  const map: Record<string, string> = {
    "aws kiro": "AWS Kiro",
    claude: "Claude",
    anthropic: "Anthropic",
    webpack: "Webpack",
    mocha: "Mocha",
    chai: "Chai",
    rspec: "RSpec",
    pgp: "PGP",
    bestcrypt: "BestCrypt",
    docker: "Docker",
    serverless: "Serverless",
    auth0: "Auth0",
    "ci/cd": "CI/CD",
    coffeescript: "CoffeeScript",
    apex: "Apex",
    knex: "Knex",
    d3: "D3.js",
    "d3.js": "D3.js",
    handsontable: "Handsontable",
    highcharts: "Highcharts",
    "passport.js": "Passport.js",
    "material-ui": "Material-UI",
  };
  return map[raw.toLowerCase()] || raw.charAt(0).toUpperCase() + raw.slice(1);
}

