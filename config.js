// Site settings: the only file to edit when the links change.
window.BENDAY = {
  // The Play listing. Until it is public, set live to false: the buttons
  // then say "Coming soon" and don't link anywhere.
  play: {
    url: 'https://play.google.com/store/apps/details?id=app.benday.reader',
    live: false,
  },

  // The public feedback tracker (a separate repository from the app's
  // code), e.g. 'https://codeberg.org/<you>/benday-feedback/issues' or
  // 'https://github.com/<you>/benday-feedback/issues'. Empty: the feedback
  // form explains that the tracker isn't up yet.
  issues: 'https://github.com/PalleKarlsson/benday/issues',

  // The closed test on Google Play (beta.html). group: the Google Group
  // testers join, e.g. 'https://groups.google.com/g/benday-testers' (the
  // group is the closed test's tester list). optIn: Play's opt-in link
  // (Testing › Closed testing › Testers › "Join on the web"). Empty group:
  // the page says sign-ups open soon.
  beta: {
    group: 'https://groups.google.com/g/benday-testers',
    optIn: '',
  },

  // Contact address for privacy questions (also in privacy.html).
  email: 'bendaydev@gmail.com',
};
