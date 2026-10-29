(() => {
  const root = document.getElementById('ss-workshop');
  const $ = selector => root.querySelector(selector);
  const fields = {name: $('#ss-name'), about: $('#ss-about'), purpose: $('#ss-purpose'), contact: $('#ss-contact'), style_preferences: $('#ss-style')};
  const steps = [...root.querySelectorAll('[data-step]')];
  let step = 0;
  let submitting = false;
  let activeRun = null;
  let revision = null;
  let pollTimer = null;

  function runError(message) {
    $('#ss-run-error').textContent = message;
    $('#ss-run-error').hidden = false;
  }

  function renderRun(result) {
    revision = result.revision;
    $('#ss-run-status').textContent = {
      running:'Planning and reviewing your recorded draft…',
      review_required:'Review required — preview and download are withheld.',
      ready:'Ready — final checks and any required review have passed.',
      failed:'The run stopped. No output is available.',
      needs_input:'More information is needed. Edit your details and submit a new run.',
      timed_out:'The run timed out. No output is available.'
    }[result.status] || 'Run unavailable.';
    $('#ss-run-events').replaceChildren();
    result.events.forEach(event => { const item = document.createElement('li'); item.textContent = event; $('#ss-run-events').append(item); });
    const review = result.status === 'review_required';
    $('#ss-review-gate').hidden = !review;
    $('#ss-run-warnings').replaceChildren();
    if (review) result.warnings.forEach(warning => {
      const label = document.createElement('h3'); label.textContent = warning.field;
      const passage = document.createElement('p'); passage.textContent = warning.passage;
      $('#ss-run-warnings').append(label, passage);
    });
    const ready = result.status === 'ready';
    $('#ss-output').hidden = !ready;
    if (ready) {
      const path = '/api/runs/' + encodeURIComponent(activeRun);
      if (!$('#ss-frame').hasAttribute('src')) $('#ss-frame').src = path + '/preview';
      $('#ss-download').href = path + '/download';
    } else {
      $('#ss-frame').removeAttribute('src');
      $('#ss-download').removeAttribute('href');
    }
  }

  async function poll(rid) {
    if (rid !== activeRun) return;
    try {
      const response = await fetch('/api/runs/' + encodeURIComponent(rid), {cache:'no-store'});
      if (!response.ok) throw new Error('Unavailable run');
      const result = await response.json();
      if (rid !== activeRun) return;
      renderRun(result);
      if (result.status === 'running') pollTimer = setTimeout(() => poll(rid), 400);
    } catch {
      if (rid === activeRun) runError('Could not retrieve this run. It may have expired or the server may have restarted. Edit your details to start again.');
    }
  }

  function clearErrors() {
    Object.values(fields).forEach(field => {
      field.removeAttribute('aria-invalid');
      const error = document.getElementById(field.id + '-error');
      error.hidden = true;
      error.textContent = '';
    });
    $('#ss-error').hidden = true;
  }

  function sync() {
    $('#ss-summary-name').textContent = fields.name.value || 'Something good starts here.';
    $('#ss-summary-about').textContent = fields.about.value || 'Your description appears here when you continue.';
    $('#ss-summary-purpose').textContent = fields.purpose.value || 'What you’d like visitors to do.';
    $('#ss-summary-style').textContent = fields.style_preferences.selectedOptions[0].textContent;
    const review = $('#ss-review');
    review.replaceChildren();
    for (const [key, label] of Object.entries({name:'Name', about:'What you do', purpose:'Visitor goal', contact:'Public contact', style_preferences:'Style'})) {
      const dt = document.createElement('dt');
      const dd = document.createElement('dd');
      dt.textContent = label;
      dd.textContent = key === 'style_preferences' ? fields[key].selectedOptions[0].textContent : fields[key].value;
      review.append(dt, dd);
    }
  }

  function show(next) {
    step = next;
    steps.forEach((panel, i) => { panel.hidden = i !== step; });
    root.querySelectorAll('.ss-steps li').forEach((item, i) => {
      if (i === step) item.setAttribute('aria-current', 'step');
      else item.removeAttribute('aria-current');
    });
    sync();
  }

  function showErrors(errors) {
    const first = Object.keys(fields).find(key => errors[key]);
    if (first) show(['name','about','purpose'].includes(first) ? 0 : 1);
    for (const [key, message] of Object.entries(errors)) {
      const field = fields[key];
      if (!field) continue;
      field.setAttribute('aria-invalid', 'true');
      const error = document.getElementById(field.id + '-error');
      error.textContent = message;
      error.hidden = false;
    }
    $('#ss-error').textContent = errors._form || 'Please correct the highlighted fields. Your other answers are still here.';
    $('#ss-error').hidden = false;
    if (first) fields[first].focus();
  }

  root.querySelectorAll('[data-next]').forEach(button => {
    button.onclick = () => {
      clearErrors();
      const keys = step === 0 ? ['name','about','purpose'] : ['contact'];
      const errors = {};
      keys.forEach(key => { if (!fields[key].value.trim()) errors[key] = 'Please complete this field.'; });
      if (Object.keys(errors).length) showErrors(errors);
      else show(step + 1);
    };
  });
  root.querySelectorAll('[data-back]').forEach(button => { button.onclick = () => { clearErrors(); show(step - 1); }; });
  $('#ss-example').onclick = () => {
    fields.name.value = 'The Corner Studio (fictional)';
    fields.about.value = 'A fictional neighborhood studio offering beginner pottery classes.';
    fields.purpose.value = 'Get in touch about a beginner class.';
    fields.contact.value = 'classes@corner-studio.example';
    clearErrors(); sync();
  };

  $('#ss-form').onsubmit = async event => {
    event.preventDefault();
    if (submitting) return;
    if (step !== 2) { root.querySelector('[data-step="' + step + '"] [data-next]').click(); return; }
    clearErrors();
    submitting = true;
    const submit = root.querySelector('[type=submit]');
    submit.disabled = true;
    submit.textContent = 'Checking your details…';
    try {
      const response = await fetch('/api/runs', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(Object.fromEntries(Object.entries(fields).map(([key, field]) => [key, field.value])))});
      const result = await response.json();
      if (response.status === 422 && result.field_errors) { showErrors(result.field_errors); return; }
      if (!response.ok || result.status !== 'running' || typeof result.request_id !== 'string') throw new Error('Unexpected run response');
      activeRun = result.request_id;
      revision = null;
      $('#ss-run-error').hidden = true;
      $('#ss-output').hidden = true;
      $('#ss-review-gate').hidden = true;
      $('#ss-frame').removeAttribute('src');
      $('#ss-run-events').replaceChildren();
      $('#ss-run-status').textContent = 'Recorded-response run started…';
      $('#ss-request-id').textContent = result.request_id;
      $('#ss-form').hidden = true;
      $('#ss-run').hidden = false;
      poll(activeRun);
    } catch {
      showErrors({_form:'We couldn’t check your brief. Make sure the local server is running and try again. Your answers are preserved.'});
    } finally {
      submitting = false;
      submit.disabled = false;
      submit.textContent = 'Create recorded draft →';
    }
  };
  $('#ss-confirm').onclick = async () => {
    const rid = activeRun;
    $('#ss-confirm').disabled = true;
    try {
      const response = await fetch('/api/runs/' + encodeURIComponent(rid) + '/confirm', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({revision})});
      if (!response.ok) throw new Error('Confirmation rejected');
      const result = await response.json();
      if (rid === activeRun) renderRun(result);
    } catch { runError('Confirmation was rejected. Refresh this run or submit an updated brief.'); }
    finally { $('#ss-confirm').disabled = false; }
  };
  $('#ss-edit').onclick = () => { activeRun = null; revision = null; clearTimeout(pollTimer); $('#ss-frame').removeAttribute('src'); $('#ss-run').hidden = true; $('#ss-form').hidden = false; clearErrors(); show(0); };
  $('#ss-privacy-toggle').onclick = () => { const panel = $('#ss-privacy'); panel.hidden = !panel.hidden; $('#ss-privacy-toggle').setAttribute('aria-expanded', String(!panel.hidden)); };
  fields.style_preferences.onchange = sync;
  show(0);
})();
