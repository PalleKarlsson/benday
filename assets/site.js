// Wires the links from config.js into the pages and builds feedback
// issues. Everything works without it except the feedback form.
(function () {
  'use strict';
  var cfg = window.BENDAY || {};
  var play = cfg.play || {};

  // Google Play buttons.
  document.querySelectorAll('[data-play]').forEach(function (a) {
    if (play.live && play.url) {
      a.href = play.url;
    } else {
      a.removeAttribute('href');
      a.setAttribute('aria-disabled', 'true');
      var label = a.querySelector('[data-play-label]');
      if (label) label.textContent = 'Coming soon to Google Play';
    }
  });
  document.querySelectorAll('[data-play-only]').forEach(function (el) {
    el.hidden = !(play.live && play.url);
  });

  // Links to the tracker; hidden while there is none.
  document.querySelectorAll('[data-issues]').forEach(function (a) {
    if (cfg.issues) a.href = cfg.issues;
    else a.hidden = true;
  });
  document.querySelectorAll('[data-issues-only]').forEach(function (el) {
    el.hidden = !cfg.issues;
  });
  document.querySelectorAll('[data-email]').forEach(function (el) {
    if (!cfg.email) return;
    el.textContent = cfg.email;
    el.classList.remove('placeholder');
  });

  // The current page in the nav.
  var here = location.pathname.split('/').pop() || 'index.html';
  document.querySelectorAll('.site-nav a').forEach(function (a) {
    if (a.getAttribute('href') === here) a.setAttribute('aria-current', 'page');
  });

  // Feedback: turn the form into a pre-filled "new issue" page on the
  // tracker (GitHub, GitLab, or Gitea/Forgejo such as Codeberg).
  var form = document.getElementById('feedback-form');
  if (!form) return;
  var status = document.getElementById('form-status');
  var submit = form.querySelector('button[type=submit]');
  var missing = document.getElementById('tracker-missing');

  if (!cfg.issues) {
    submit.disabled = true;
    if (missing) missing.hidden = false;
  }

  var labels = { bug: 'bug', idea: 'enhancement', question: 'question' };
  var prefixes = { bug: 'Bug', idea: 'Idea', question: 'Question' };

  function value(name) {
    var el = form.elements[name];
    return el ? String(el.value || '').trim() : '';
  }

  function issueUrl(kind, title, body) {
    var base = cfg.issues.replace(/\/+$/, '');
    var host = '';
    try { host = new URL(base).hostname; } catch (e) { /* relative */ }
    var q;
    if (host === 'github.com') {
      q = 'title=' + encodeURIComponent(title) + '&body=' + encodeURIComponent(body) +
        '&labels=' + encodeURIComponent(labels[kind]);
    } else if (/gitlab/.test(host)) {
      q = 'issue[title]=' + encodeURIComponent(title) +
        '&issue[description]=' + encodeURIComponent(body);
    } else {
      q = 'title=' + encodeURIComponent(title) + '&body=' + encodeURIComponent(body);
    }
    return base + '/new?' + q;
  }

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    if (!cfg.issues) return;
    var kind = value('kind') || 'bug';
    var summary = value('title');
    var details = value('details');
    if (!summary || !details) {
      status.textContent = 'Add a short summary and some details first.';
      return;
    }
    var lines = [details, ''];
    var facts = [
      ['Benday version', value('app')],
      ['Android / device', value('device')],
      ['Komga version', value('komga')],
    ].filter(function (f) { return f[1]; });
    if (facts.length) {
      lines.push('---');
      facts.forEach(function (f) { lines.push('**' + f[0] + ':** ' + f[1]); });
    }
    lines.push('', '_Sent from the Benday website._');
    var url = issueUrl(kind, prefixes[kind] + ': ' + summary, lines.join('\n'));
    status.textContent = 'Opening the tracker in a new tab. Sign in there and press Create.';
    window.open(url, '_blank', 'noopener');
  });
})();
