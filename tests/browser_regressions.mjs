// Run using the connected browser tool with an isolated e2e_fixture.py tab.
// These checks never create accounts, accept quotes or approve production work.
export async function assertFreshApprovalRequired(tab) {
  const button = tab.playwright.getByRole('button', { name: 'Approve concept', exact: true });
  const checkbox = tab.playwright.getByRole('checkbox', { name: /I approve this concept version/ });
  const checked = await checkbox.evaluate(element => element.checked);
  if (checked || await button.isEnabled()) {
    throw new Error('A changed preview still carries the previous version approval.');
  }
  return 'PASS changed_preview_requires_fresh_checkbox';
}

export async function assertFailedPreviewIsHonest(tab) {
  const alerts = await tab.playwright.getByRole('alert').allTextContents({ timeoutMs: 1000 });
  if (!alerts.some(text => /génération.*échoué|résultat.*confirmé/i.test(text))) {
    throw new Error('Failed generation does not show an explicit failure state.');
  }
  if (await tab.playwright.getByText(/aperçu de démonstration/).count()) {
    throw new Error('Failed generation is displayed as a demonstration preview.');
  }
  if (!await tab.playwright.getByRole('button', { name: 'Réessayer la génération', exact: true }).isEnabled()) {
    throw new Error('Explicit generation retry is unavailable.');
  }
  return 'PASS failed_generation_has_error_and_explicit_retry';
}
