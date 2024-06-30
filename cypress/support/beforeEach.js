beforeEach(function() {
  // Reset DB before each test
  // TODO: find a faster way to do this.
  cy.exec(
    "docker compose run django sh -c './manage.py flush --noinput && ./manage.py generate_test_data'"
  );
});
