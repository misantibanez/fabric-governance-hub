import assert from "node:assert/strict";
import fs from "node:fs/promises";

const API_URL = "https://api.github.com";

export function issueNumberFromBranch(branch) {
  const match = /^feature\/(?:issue[-_/]?)?(\d+)(?:[-_/].*)?$/i.exec(branch);
  return match ? Number(match[1]) : null;
}

export function transitionFromEvent(eventName, event) {
  if (eventName === "create" && event.ref_type === "branch") {
    const issueNumber = issueNumberFromBranch(event.ref);
    return issueNumber ? { issueNumbers: [issueNumber], status: "inProgress" } : null;
  }

  const pullRequest = event.pull_request;
  if (eventName !== "pull_request" || !pullRequest?.merged) {
    return null;
  }

  if (pullRequest.base.ref === "develop") {
    const issueNumber = issueNumberFromBranch(pullRequest.head.ref);
    return issueNumber ? { issueNumbers: [issueNumber], status: "inReview" } : null;
  }

  if (pullRequest.base.ref === "main" && pullRequest.head.ref === "develop") {
    return { issueNumbers: null, status: "done" };
  }

  return null;
}

async function githubRequest(token, path, options = {}) {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${token}`,
      "User-Agent": "fabric-governance-hub-project-automation",
      "X-GitHub-Api-Version": "2022-11-28",
      ...options.headers,
    },
  });

  if (!response.ok) {
    throw new Error(`GitHub API ${response.status} for ${path}: ${await response.text()}`);
  }

  return response.json();
}

async function graphql(token, query, variables) {
  const result = await githubRequest(token, "/graphql", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, variables }),
  });

  if (result.errors?.length) {
    throw new Error(`GitHub GraphQL error: ${JSON.stringify(result.errors)}`);
  }

  return result.data;
}

async function promotedIssueNumbers(token, repository, pullRequest) {
  const [owner, repo] = repository.split("/");
  const issueNumbers = new Set();
  let page = 1;

  while (true) {
    const comparison = await githubRequest(
      token,
      `/repos/${owner}/${repo}/compare/${pullRequest.base.sha}...${pullRequest.merge_commit_sha}?per_page=100&page=${page}`,
    );

    for (const commit of comparison.commits) {
      const pullRequests = await githubRequest(
        token,
        `/repos/${owner}/${repo}/commits/${commit.sha}/pulls`,
      );

      for (const associatedPullRequest of pullRequests) {
        if (associatedPullRequest.merged_at && associatedPullRequest.base.ref === "develop") {
          const issueNumber = issueNumberFromBranch(associatedPullRequest.head.ref);
          if (issueNumber) {
            issueNumbers.add(issueNumber);
          }
        }
      }
    }

    if (comparison.commits.length < 100) {
      break;
    }
    page += 1;
  }

  return [...issueNumbers];
}

async function updateIssueStatus(token, repository, issueNumber, configuration, status) {
  const [owner, repo] = repository.split("/");
  const issueData = await graphql(
    token,
    `query($owner: String!, $repo: String!, $issueNumber: Int!) {
      repository(owner: $owner, name: $repo) {
        issue(number: $issueNumber) {
          id
          projectItems(first: 100) { nodes { id project { id } } }
        }
      }
    }`,
    { owner, repo, issueNumber },
  );
  const issue = issueData.repository?.issue;
  if (!issue) {
    throw new Error(`Issue #${issueNumber} was not found in ${repository}`);
  }

  let itemId = issue.projectItems.nodes.find(
    (item) => item.project.id === configuration.projectId,
  )?.id;

  if (!itemId) {
    const added = await graphql(
      token,
      `mutation($projectId: ID!, $contentId: ID!) {
        addProjectV2ItemById(input: { projectId: $projectId, contentId: $contentId }) {
          item { id }
        }
      }`,
      { projectId: configuration.projectId, contentId: issue.id },
    );
    itemId = added.addProjectV2ItemById.item.id;
  }

  await graphql(
    token,
    `mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
      updateProjectV2ItemFieldValue(input: {
        projectId: $projectId,
        itemId: $itemId,
        fieldId: $fieldId,
        value: { singleSelectOptionId: $optionId }
      }) { projectV2Item { id } }
    }`,
    {
      projectId: configuration.projectId,
      itemId,
      fieldId: configuration.statusFieldId,
      optionId: configuration.statusOptions[status],
    },
  );

  console.log(`Updated issue #${issueNumber} to ${status}`);
}

function runSelfTest() {
  assert.equal(issueNumberFromBranch("feature/12-persistent-shared-settings"), 12);
  assert.equal(issueNumberFromBranch("feature/issue-42-add-audit-log"), 42);
  assert.equal(issueNumberFromBranch("fix/12-not-a-feature"), null);
  assert.deepEqual(
    transitionFromEvent("create", { ref_type: "branch", ref: "feature/12-settings" }),
    { issueNumbers: [12], status: "inProgress" },
  );
  assert.deepEqual(
    transitionFromEvent("pull_request", {
      pull_request: { merged: true, base: { ref: "develop" }, head: { ref: "feature/12-settings" } },
    }),
    { issueNumbers: [12], status: "inReview" },
  );
  assert.deepEqual(
    transitionFromEvent("pull_request", {
      pull_request: { merged: true, base: { ref: "main" }, head: { ref: "develop" } },
    }),
    { issueNumbers: null, status: "done" },
  );
  console.log("Project status transition tests passed");
}

async function main() {
  if (process.argv.includes("--self-test")) {
    runSelfTest();
    return;
  }

  const eventVariables = ["GITHUB_EVENT_NAME", "GITHUB_EVENT_PATH"];
  const missingEventVariables = eventVariables.filter((name) => !process.env[name]);
  if (missingEventVariables.length) {
    throw new Error(`Missing required environment variables: ${missingEventVariables.join(", ")}`);
  }

  const event = JSON.parse(await fs.readFile(process.env.GITHUB_EVENT_PATH, "utf8"));
  const transition = transitionFromEvent(process.env.GITHUB_EVENT_NAME, event);
  if (!transition) {
    console.log("Event does not match a project status transition");
    return;
  }

  const requiredVariables = [
    "GITHUB_REPOSITORY",
    "PROJECT_V2_TOKEN",
    "PROJECT_ID",
    "PROJECT_STATUS_FIELD_ID",
    "PROJECT_STATUS_IN_PROGRESS_ID",
    "PROJECT_STATUS_IN_REVIEW_ID",
    "PROJECT_STATUS_DONE_ID",
  ];
  const missingVariables = requiredVariables.filter((name) => !process.env[name]);
  if (missingVariables.length) {
    throw new Error(`Missing required environment variables: ${missingVariables.join(", ")}`);
  }

  const configuration = {
    projectId: process.env.PROJECT_ID,
    statusFieldId: process.env.PROJECT_STATUS_FIELD_ID,
    statusOptions: {
      inProgress: process.env.PROJECT_STATUS_IN_PROGRESS_ID,
      inReview: process.env.PROJECT_STATUS_IN_REVIEW_ID,
      done: process.env.PROJECT_STATUS_DONE_ID,
    },
  };
  const issueNumbers = transition.issueNumbers ?? await promotedIssueNumbers(
    process.env.PROJECT_V2_TOKEN,
    process.env.GITHUB_REPOSITORY,
    event.pull_request,
  );

  if (!issueNumbers.length) {
    console.log("No issue-based feature branches were found in the promotion");
    return;
  }

  for (const issueNumber of issueNumbers) {
    await updateIssueStatus(
      process.env.PROJECT_V2_TOKEN,
      process.env.GITHUB_REPOSITORY,
      issueNumber,
      configuration,
      transition.status,
    );
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});