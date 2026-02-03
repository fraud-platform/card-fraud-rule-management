// Load Test Script for Card Fraud Rule Management API
// Uses k6 for HTTP load testing
// Install: winget install k6
// Run: k6 run scripts/load_test.js

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';

// Custom metrics
const errorRate = new Rate('errors');
const createRuleDuration = new Trend('create_rule_duration');
const compileDuration = new Trend('compile_duration');
const approveDuration = new Trend('approve_duration');
const rulesPublished = new Counter('rules_published');

// Test configuration
export const options = {
  scenarios: {
    // Scenario 1: Create and publish rules (sequential)
    create_and_publish: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 10 },   // Ramp up
        { duration: '1m', target: 10 },    // Stay at 10
        { duration: '30s', target: 0 },    // Ramp down
      ],
      gracefulRampDown: '10s',
      exec: 'createAndPublishRules',
    },
    
    // Scenario 2: Read-heavy (list rules, get rulesets)
    read_operations: {
      executor: 'constant-arrival-rate',
      rate: 50,
      timeUnit: '1s',
      duration: '2m',
      preAllocatedVUs: 20,
      maxVUs: 50,
      exec: 'readOperations',
    },
    
    // Scenario 3: Compile and approve (maker-checker workflow)
    compile_and_approve: {
      executor: 'per-vu-iterations',
      iterations: 5,
      vus: 5,
      maxDuration: '5m',
      exec: 'compileAndApprove',
    },
  },
  
  thresholds: {
    http_req_duration: ['p(95)<500'],     // 95% of requests under 500ms
    http_req_failed: ['rate<0.01'],       // Less than 1% errors
    errors: ['rate<0.05'],                // Less than 5% custom errors
  },
};

const BASE_URL = __ENV.API_URL || 'http://127.0.0.1:8000';
const MAKER_TOKEN = __ENV.MAKER_TOKEN || '';
const CHECKER_TOKEN = __ENV.CHECKER_TOKEN || '';

const headers = {
  'Content-Type': 'application/json',
};

// Test data - realistic production-like rules
const ruleTemplates = [
  {
    name: 'High Value Transaction',
    type: 'AUTH',
    condition: { logicalOperator: 'AND', conditions: [
      { field: 'amount', operator: 'GT', value: 10000 },
      { field: 'currency', operator: 'EQ', value: 'USD' },
    ]},
    priority: 100,
  },
  {
    name: 'High Risk MCC',
    type: 'BLOCKLIST',
    condition: { field: 'mcc', operator: 'IN', value: ['5967', '7995', '5816'] },
    priority: 200,
  },
  {
    name: 'International Transaction',
    type: 'MONITORING',
    condition: { logicalOperator: 'AND', conditions: [
      { field: 'country', operator: 'NE', value: 'US' },
      { field: 'amount', operator: 'GT', value: 500 },
    ]},
    priority: 150,
  },
  {
    name: 'High Velocity Card',
    type: 'AUTH',
    condition: { logicalOperator: 'AND', conditions: [
      { field: 'velocity_txn_count_1h', operator: 'GT', value: 10 },
      { field: 'amount', operator: 'GT', value: 1000 },
    ]},
    priority: 300,
  },
];

function authHeader(token) {
  return { ...headers, 'Authorization': `Bearer ${token}` };
}

export function createAndPublishRules() {
  if (!MAKER_TOKEN || !CHECKER_TOKEN) {
    console.log('SKIP: MAKER_TOKEN and CHECKER_TOKEN required');
    return;
  }

  const template = ruleTemplates[Math.floor(Math.random() * ruleTemplates.length)];
  const ruleName = `${template.name} ${Date.now()} ${__VU}`;

  // Step 1: Create Rule
  group('Create Rule', function() {
    const start = Date.now();
    const createRes = http.post(
      `${BASE_URL}/api/v1/rules`,
      JSON.stringify({
        rule_name: ruleName,
        description: `Load test - ${template.name}`,
        rule_type: template.type,
      }),
      { headers: authHeader(MAKER_TOKEN) }
    );
    createRuleDuration.add(Date.now() - start);

    const passed = check(createRes, {
      'rule created': (r) => r.status === 201 || r.status === 409,
      'has rule_id': (r) => r.json('rule_id') !== undefined,
    });
    errorRate.add(!passed);

    if (createRes.status !== 201) return;
    
    const ruleId = createRes.json('rule_id');

    // Step 2: Create Rule Version
    const versionRes = http.post(
      `${BASE_URL}/api/v1/rules/${ruleId}/versions`,
      JSON.stringify({
        condition_tree: template.condition,
        priority: template.priority + __VU,
        scope: { network: ['VISA', 'MASTERCARD'] },
      }),
      { headers: authHeader(MAKER_TOKEN) }
    );

    if (versionRes.status !== 201) return;
    const ruleVersionId = versionRes.json('rule_version_id');

    // Step 3: Create RuleSet (reuse existing if possible)
    const rulesetName = `Load Test AUTH ${Date.now().toString().slice(0, 8)}`;
    let rulesetId;
    
    const rulesetRes = http.post(
      `${BASE_URL}/api/v1/rulesets`,
      JSON.stringify({
        environment: 'local',
        region: 'LOADTEST',
        country: 'XX',
        rule_type: 'AUTH',
        name: rulesetName,
        description: 'Load test ruleset',
      }),
      { headers: authHeader(MAKER_TOKEN) }
    );

    if (rulesetRes.status === 201) {
      rulesetId = rulesetRes.json('ruleset_id');
    } else {
      // Find existing ruleset
      const listRes = http.get(
        `${BASE_URL}/api/v1/rulesets?environment=local&region=LOADTEST&rule_type=AUTH&limit=1`,
        { headers: authHeader(MAKER_TOKEN) }
      );
      if (listRes.json('items.0.ruleset_id')) {
        rulesetId = listRes.json('items.0.ruleset_id');
      }
    }

    if (!rulesetId) return;

    // Step 4: Create RuleSet Version
    const rsVersionRes = http.post(
      `${BASE_URL}/api/v1/rulesets/${rulesetId}/versions`,
      JSON.stringify({ rule_version_ids: [ruleVersionId] }),
      { headers: authHeader(MAKER_TOKEN) }
    );

    if (rsVersionRes.status !== 201) return;
    const rsVersionId = rsVersionRes.json('ruleset_version_id');

    // Step 5: Submit for Approval
    http.post(
      `${BASE_URL}/api/v1/ruleset-versions/${rsVersionId}/submit`,
      JSON.stringify({ idempotency_key: `submit_${rsVersionId}` }),
      { headers: authHeader(MAKER_TOKEN) }
    );

    // Step 6: Approve (triggers compile + S3 publish)
    const approveStart = Date.now();
    const approveRes = http.post(
      `${BASE_URL}/api/v1/ruleset-versions/${rsVersionId}/approve`,
      JSON.stringify({ idempotency_key: `approve_${rsVersionId}` }),
      { headers: authHeader(CHECKER_TOKEN) }
    );
    approveDuration.add(Date.now() - approveStart);

    if (approveRes.status === 200) {
      rulesPublished.add(1);
      console.log(`Published ruleset: ${rsVersionId}`);
    }
  });

  sleep(1);
}

export function readOperations() {
  // List rules
  const rulesRes = http.get(
    `${BASE_URL}/api/v1/rules?limit=20`,
    { headers: headers }
  );
  
  check(rulesRes, {
    'rules listed': (r) => r.status === 200,
  });

  // List rulesets
  const rulesetsRes = http.get(
    `${BASE_URL}/api/v1/rulesets?limit=10`,
    { headers: headers }
  );
  
  check(rulesetsRes, {
    'rulesets listed': (r) => r.status === 200,
  });

  // Get single rule
  if (rulesRes.json('items.0.rule_id')) {
    const ruleId = rulesRes.json('items.0.rule_id');
    http.get(
      `${BASE_URL}/api/v1/rules/${ruleId}`,
      { headers: headers }
    );
  }

  sleep(0.5);
}

export function compileAndApprove() {
  if (!MAKER_TOKEN || !CHECKER_TOKEN) {
    console.log('SKIP: Tokens required');
    return;
  }

  // Find DRAFT ruleset versions and compile them
  const res = http.get(
    `${BASE_URL}/api/v1/ruleset-versions?status=DRAFT&limit=5`,
    { headers: authHeader(MAKER_TOKEN) }
  );

  if (res.status !== 200) return;

  const versions = res.json('items') || [];
  
  for (const version of versions) {
    const rsVersionId = version.ruleset_version_id;

    // Compile
    const compileStart = Date.now();
    const compileRes = http.post(
      `${BASE_URL}/api/v1/ruleset-versions/${rsVersionId}/compile`,
      null,
      { headers: authHeader(MAKER_TOKEN) }
    );
    compileDuration.add(Date.now() - compileStart);

    if (compileRes.status !== 200) continue;

    // Submit
    http.post(
      `${BASE_URL}/api/v1/ruleset-versions/${rsVersionId}/submit`,
      JSON.stringify({ idempotency_key: `submit_${rsVersionId}` }),
      { headers: authHeader(MAKER_TOKEN) }
    );

    // Approve
    const approveStart = Date.now();
    const approveRes = http.post(
      `${BASE_URL}/api/v1/ruleset-versions/${rsVersionId}/approve`,
      JSON.stringify({ idempotency_key: `approve_${rsVersionId}` }),
      { headers: authHeader(CHECKER_TOKEN) }
    );
    approveDuration.add(Date.now() - approveStart);

    if (approveRes.status === 200) {
      rulesPublished.add(1);
    }
  }
}

export function handleSummary(data) {
  return {
    'stdout': summary(data),
    'reports/load_test_summary.json': JSON.stringify(data, null, 2),
  };
}

function summary(data) {
  const { metrics } = data;
  return `
========================================
LOAD TEST SUMMARY
========================================

Requests:
  - Total: ${metrics.http_reqs.values.count}
  - Failed: ${metrics.http_req_failed.values.rate * 100:.2f}%
  - 95th percentile: ${metrics.http_req_duration.values['p(95)']}ms

Custom Metrics:
  - Create Rule Avg: ${metrics.create_rule_duration.values.avg}ms
  - Compile Avg: ${metrics.compile_duration.values.avg}ms
  - Approve Avg: ${metrics.approve_duration.values.avg}ms
  - Rules Published: ${metrics.rules_published.values.count}

Errors: ${metrics.errors.values.rate * 100:.2f}%

========================================
`;
}
