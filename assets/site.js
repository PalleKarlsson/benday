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
  var beta = cfg.beta || {};
  document.querySelectorAll('[data-beta-group]').forEach(function (a) {
    if (beta.group) a.href = beta.group;
  });
  document.querySelectorAll('[data-beta-optin]').forEach(function (a) {
    if (beta.optIn) a.href = beta.optIn;
  });
  document.querySelectorAll('[data-beta-open]').forEach(function (el) {
    el.hidden = !beta.group;
  });
  document.querySelectorAll('[data-beta-closed]').forEach(function (el) {
    el.hidden = !!beta.group;
  });
  document.querySelectorAll('[data-beta-optin-only]').forEach(function (el) {
    el.hidden = !beta.optIn;
  });
  document.querySelectorAll('[data-beta-optin-missing]').forEach(function (el) {
    el.hidden = !!beta.optIn;
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
      form.elements[summary ? 'details' : 'title'].focus();
      return;
    }
    var title = prefixes[kind] + ': ' + summary;
    var body = issueBody(details);
    var url = issueUrl(kind, title, body);
    // Trackers refuse very long URLs (GitHub: about 8 000 characters):
    // send what fits and put the full text on the clipboard.
    var trimmed = false;
    if (url.length > MAX_URL) {
      trimmed = true;
      var note = '\n\n_(Cut short: paste the rest of the details here.)_';
      var keep = details.length;
      do {
        keep = Math.floor(keep * 0.8);
        body = issueBody(details.slice(0, keep) + note);
        url = issueUrl(kind, title, body);
      } while (url.length > MAX_URL && keep > 0);
      if (navigator.clipboard) navigator.clipboard.writeText(details).catch(function () {});
    }
    status.textContent = trimmed
      ? 'Your details were too long for one link: the full text is on your clipboard. Paste the rest into the issue, then press Create.'
      : 'Opening the tracker in a new tab. Sign in there and press Create.';
    window.open(url, '_blank', 'noopener');
  });

  var MAX_URL = 7500;

  function issueBody(details) {
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
    return lines.join('\n');
  }
})();
