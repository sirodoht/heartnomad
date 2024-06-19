/// <reference types='Cypress' />

describe('Billing', () => {
  it('works when adding credit card to profile', () => {
    cy.login('pixel', 'password');
    cy.visit('/people/pixel/');
    cy.contains('Add Credit Card').click();
    
    cy.origin('https://checkout.stripe.com', () => {
      cy.get('#cardNumber').type('4242424242424242');
      cy.get('#cardExpiry').type('01/30');
      cy.get('#cardCvc').type('313');
      cy.get('#billingName').type('Anna Bob');
      cy.get('#billingCountry').select('US');
      cy.get('#billingPostalCode').type('94122');
      cy.get('button.SubmitButton').click();
    });

    cy.login('pixel', 'password');
    cy.visit('/people/pixel/');
    cy.contains('Delete Card').click();
    cy.contains('Card deleted.');
    cy.contains('Add Credit Card');
  });
});
