(() => {
  const root = document.getElementById('ss-workshop');
  const $ = selector => root.querySelector(selector);
  const fields = {name: $('#ss-name'), about: $('#ss-about'), purpose: $('#ss-purpose'), contact: $('#ss-contact'), style_preferences: $('#ss-style')};
  const steps = [...root.querySelectorAll('[data-step]')];
  let step = 0;
  let submitting = false;

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
      const response = await fetch('/api/brief', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(Object.fromEntries(Object.entries(fields).map(([key, field]) => [key, field.value])))});
      const result = await response.json();
      if (response.status === 422 && result.field_errors) { showErrors(result.field_errors); return; }
      if (!response.ok || result.status !== 'accepted' || typeof result.request_id !== 'string') throw new Error('Unexpected validation response');
      $('#ss-request-id').textContent = result.request_id;
      $('#ss-form').hidden = true;
      $('#ss-run').hidden = false;
    } catch {
      showErrors({_form:'We couldn’t check your brief. Make sure the local server is running and try again. Your answers are preserved.'});
    } finally {
      submitting = false;
      submit.disabled = false;
      submit.textContent = 'Check my brief →';
    }
  };
  $('#ss-edit').onclick = () => { $('#ss-run').hidden = true; $('#ss-form').hidden = false; clearErrors(); show(0); };
  $('#ss-privacy-toggle').onclick = () => { const panel = $('#ss-privacy'); panel.hidden = !panel.hidden; $('#ss-privacy-toggle').setAttribute('aria-expanded', String(!panel.hidden)); };
  fields.style_preferences.onchange = sync;
  show(0);
})();
