/**
 * Civic Bridge — 3-page flow
 * Page 1: Message + Name + Email
 * Page 2: Address + Confirm + Send
 * Page 3: Results + Call follow-up
 */
(function() {
    'use strict';

    const $ = (id) => document.getElementById(id);

    // Pages
    const pageMessage = $('page-message');
    const pageAddress = $('page-address');
    const pageResults = $('page-results');

    // Page 1: Message
    const messageEl = $('message');
    const charCount = $('char-count');
    const btnToAddress = $('btn-to-address');

    // Page 2: Address
    const addressInput = $('address');
    const autocompleteList = $('autocomplete-list');
    const confirmArea = $('confirm-area');
    const confirmReps = $('confirm-reps');
    const captchaArea = $('captcha-area');
    const captchaContainer = $('captcha-container');
    const callSection = $('call-section');
    const callScript = $('call-script');
    const addressForm = $('address-form');
    const btnSend = $('btn-send');
    const btnAddrBack = $('btn-addr-back');

    // Page 3: Results
    const resultTitle = $('result-title');
    const resultList = $('result-list');
    const resultWarnings = $('result-warnings');
    const resultCall = $('result-call');
    const btnNewMessage = $('btn-new-message');

    // State
    let previewData = null;
    let captchaTokens = {};
    let captchaWidgets = {};
    let autocompleteTimer = null;
    let callScriptData = null;

    // ---- Character counter ----
    messageEl.addEventListener('input', function() {
        var len = this.value.length;
        charCount.textContent = len + ' / 5000';
        charCount.style.color = len > 4500 ? 'var(--red-light)' : len > 4000 ? '#eab308' : '';
    });

    var sendTo = 'all';

    // ---- Send-to button toggle ----
    var toggles = document.querySelectorAll('.btn-toggle');
    toggles.forEach(function(btn) {
        btn.addEventListener('click', function() {
            toggles.forEach(function(b) { b.classList.remove('active'); });
            this.classList.add('active');
            sendTo = this.getAttribute('data-value');
        });
    });
    function goTo(from, to) {
        from.style.display = 'none';
        to.style.display = '';
        to.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    // ---- Page 1 → Page 2 ----
    btnToAddress.addEventListener('click', function() {
        var msg = messageEl.value.trim();
        var first = $('first_name').value.trim();
        var last = $('last_name').value.trim();
        var email = $('email').value.trim();

        if (!msg) { shake(messageEl); messageEl.focus(); return; }
        if (!first) { shake($('first_name')); $('first_name').focus(); return; }
        if (!last) { shake($('last_name')); $('last_name').focus(); return; }
        if (!email || email.indexOf('@') === -1) { shake($('email')); $('email').focus(); return; }

        goTo(pageMessage, pageAddress);
        addressInput.focus();
    });

    // ---- Address Autocomplete ----
    addressInput.addEventListener('input', function() {
        clearTimeout(autocompleteTimer);
        var q = this.value.trim();
        if (q.length < 3) {
            autocompleteList.innerHTML = '';
            autocompleteList.style.display = 'none';
            return;
        }
        autocompleteTimer = setTimeout(function() { fetchAutocomplete(q); }, 300);
    });

    addressInput.addEventListener('blur', function() {
        setTimeout(function() { autocompleteList.style.display = 'none'; }, 200);
    });

    addressInput.addEventListener('focus', function() {
        if (autocompleteList.children.length > 0) autocompleteList.style.display = '';
    });

    function fetchAutocomplete(q) {
        fetch('/api/autocomplete?q=' + encodeURIComponent(q))
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var suggestions = data.suggestions || [];
                if (!suggestions.length) {
                    autocompleteList.style.display = 'none';
                    return;
                }
                autocompleteList.innerHTML = suggestions.map(function(s) {
                    return '<div class="autocomplete-item" role="option">' + escHtml(s) + '</div>';
                }).join('');
                autocompleteList.style.display = '';
                autocompleteList.querySelectorAll('.autocomplete-item').forEach(function(item) {
                    item.addEventListener('mousedown', function(e) {
                        e.preventDefault();
                        addressInput.value = item.textContent;
                        autocompleteList.style.display = 'none';
                    });
                });
            })
            .catch(function() {});
    }

    // ---- Page 2: Submit → preview → show confirm ----
    addressForm.addEventListener('submit', function(e) {
        e.preventDefault();
        var addr = addressInput.value.trim();
        if (!addr) { shake(addressInput); return; }

        btnSend.disabled = true;
        btnSend.querySelector('.btn-label').textContent = 'Sending...';
        btnSend.classList.add('is-sending');

        var fd = new FormData();
        fd.append('message', messageEl.value);
        fd.append('address', addr);
        fd.append('first_name', $('first_name').value.trim());
        fd.append('last_name', $('last_name').value.trim());
        fd.append('email', $('email').value.trim());
        fd.append('topic', $('topic').value);
        fd.append('send_to', sendTo);

        fetch('/api/preview', { method: 'POST', body: fd })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.error) {
                    btnSend.disabled = false;
                    btnSend.querySelector('.btn-label').textContent = 'Send my message';
                    btnSend.classList.remove('is-sending');
                    addressInput.style.borderColor = 'var(--red)';
                    var msg = data.error;
                    if (data.details && data.details.length) {
                        msg += '\n\n' + data.details.join('\n');
                    }
                    alert(msg);
                    setTimeout(function() { addressInput.style.borderColor = ''; }, 2000);
                    return;
                }
                previewData = data;
                renderConfirm(data);
                confirmArea.style.display = '';
                confirmArea.scrollIntoView({ behavior: 'smooth', block: 'start' });
            })
            .catch(function() {
                btnSend.disabled = false;
                btnSend.querySelector('.btn-label').textContent = 'Send my message';
                btnSend.classList.remove('is-sending');
                alert('Connection error. Please try again.');
            });
    });

    function renderConfirm(data) {
        var reps = data.representatives || [];
        confirmReps.innerHTML = reps.map(function(r) {
            return '<div class="confirm-rep">' +
                '<span class="confirm-chamber ' + (r.chamber === 'senate' ? 'chamber-senate' : 'chamber-house') + '">' + (r.chamber === 'senate' ? 'Senate' : 'House') + '</span>' +
                '<strong>' + escHtml(r.name) + '</strong>' +
                '<span class="confirm-state">' + r.state + (r.party ? ' \u00b7 ' + r.party : '') + '</span>' +
                '</div>';
        }).join('');

        // Build call script
        var zip = '';
        if (data.address) {
            var parts = data.address.split(',');
            var last = parts[parts.length - 1].trim().split(' ');
            zip = last[last.length - 1] || '';
        }
        callScriptData = reps.map(function(r) {
            return { name: r.name, phone: r.phone || 'See website' };
        });
        callScript.innerHTML =
            '<div class="call-script-intro"><p>A phone call takes 2 minutes and is the most effective way to be heard:</p></div>' +
            '<div class="call-script-text"><p>"Hello, my name is <strong>' + escHtml($('first_name').value || '___') + ' ' + escHtml($('last_name').value || '___') + '</strong>. I am a constituent from ZIP code <strong>' + zip + '</strong>. I submitted a comment about <strong>' + escHtml($('topic').value) + '</strong> and wanted to follow up. Please ensure my position is registered with the ' + (reps[0] && reps[0].chamber === 'senate' ? 'Senator' : 'Representative') + '."</p></div>' +
            '<div class="call-numbers">' + callScriptData.map(function(r) { return '<p><strong>' + escHtml(r.name) + ':</strong> ' + escHtml(r.phone) + '</p>'; }).join('') + '</div>';
        callSection.style.display = '';

        // Captcha
        var needed = data.captchas_needed || [];
        if (needed.length > 0) {
            captchaArea.style.display = '';
            captchaContainer.innerHTML = '';
            captchaTokens = {};
            captchaWidgets = {};
            needed.forEach(function(c, i) {
                var div = document.createElement('div');
                div.className = 'captcha-widget';
                div.innerHTML = '<p class="captcha-label">For: ' + c.representatives.join(', ') + '</p><div class="captcha-render" id="captcha-render-' + i + '"></div>';
                captchaContainer.appendChild(div);
                setTimeout(function() { renderCaptchaWidget(i, c); }, 150);
            });
        } else {
            captchaArea.style.display = 'none';
        }

        // Change button to confirm mode
        btnSend.querySelector('.btn-label').textContent = 'Confirm & send';
        btnSend.disabled = false;
        btnSend.classList.remove('is-sending');
        btnSend.setAttribute('data-mode', 'confirm');
    }

    function renderCaptchaWidget(index, captcha) {
        var el = document.getElementById('captcha-render-' + index);
        if (!el) return;
        var cbName = 'ccb_' + index + '_' + Date.now();
        window[cbName] = function(token) {
            captchaTokens[captcha.sitekey] = token;
            var widget = el.closest('.captcha-widget');
            if (widget) widget.style.opacity = '0.5';
        };
        try {
            if (captcha.type === 'recaptcha_v2') {
                captchaWidgets[captcha.sitekey] = grecaptcha.render('captcha-render-' + index, { sitekey: captcha.sitekey, callback: cbName, theme: 'dark' });
            } else if (captcha.type === 'hcaptcha') {
                captchaWidgets[captcha.sitekey] = hcaptcha.render('captcha-render-' + index, { sitekey: captcha.sitekey, callback: cbName, theme: 'dark' });
            } else if (captcha.type === 'turnstile') {
                captchaWidgets[captcha.sitekey] = turnstile.render('captcha-render-' + index, { sitekey: captcha.sitekey, callback: cbName, theme: 'dark' });
            } else {
                captchaTokens[captcha.sitekey] = 'bypass';
            }
        } catch (err) {
            captchaTokens[captcha.sitekey] = 'fallback';
        }
    }

    // ---- Confirm → Actual send ----
    btnSend.addEventListener('click', function() {
        if (btnSend.getAttribute('data-mode') !== 'confirm') return; // Only in confirm mode

        var needed = previewData ? (previewData.captchas_needed || []) : [];
        var unsolved = needed.filter(function(c) { return !captchaTokens[c.sitekey]; });
        if (unsolved.length > 0) {
            alert('Please complete all verifications before sending.');
            return;
        }

        btnSend.disabled = true;
        btnSend.querySelector('.btn-label').textContent = 'Sending...';
        btnSend.classList.add('is-sending');

        var fd = new FormData();
        fd.append('message', messageEl.value);
        fd.append('address', addressInput.value.trim());
        fd.append('first_name', $('first_name').value.trim());
        fd.append('last_name', $('last_name').value.trim());
        fd.append('email', $('email').value.trim());
        fd.append('topic', $('topic').value);
        fd.append('send_to', sendTo);
        fd.append('captcha_tokens', JSON.stringify(captchaTokens));

        fetch('/api/send', { method: 'POST', body: fd })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                renderResults(data);
                goTo(pageAddress, pageResults);
            })
            .catch(function() {
                alert('Connection error.');
                btnSend.disabled = false;
                btnSend.querySelector('.btn-label').textContent = 'Confirm & send';
                btnSend.classList.remove('is-sending');
            });
    });

    btnAddrBack.addEventListener('click', function() {
        goTo(pageAddress, pageMessage);
    });

    // ---- Results ----
    function renderResults(data) {
        var reps = data.representatives || [];
        var delivered = reps.filter(function(r) { return r.status === 'delivered'; }).length;
        var total = reps.length;

        if (delivered === total) {
            resultTitle.textContent = 'Sent to ' + total + ' representative' + (total !== 1 ? 's' : '') + '!';
        } else if (delivered > 0) {
            resultTitle.textContent = 'Sent to ' + delivered + ' of ' + total + ' representatives';
        } else {
            resultTitle.textContent = 'Delivery could not be completed';
        }

        var icons = { delivered: '\u2713', failed: '\u2717', skipped: '\u2298', no_form: '?', captcha_needed: '\uD83D\uDD12' };
        resultList.innerHTML = reps.map(function(r) {
            var cl = r.chamber === 'senate' ? 'chamber-senate' : 'chamber-house';
            var lb = r.chamber === 'senate' ? 'Senate' : 'House';
            return '<div class="result-item">' +
                '<div class="result-icon ' + r.status + '">' + (icons[r.status] || '?') + '</div>' +
                '<div class="result-body"><div class="result-name">' + escHtml(r.name) + '</div>' +
                '<div class="result-detail">' + escHtml(r.error || (r.status === 'delivered' ? 'Message sent' : '')) + '</div></div>' +
                '<span class="result-chamber ' + cl + '">' + lb + '</span></div>';
        }).join('');

        // Call follow-up
        if (callScriptData) {
            resultCall.style.display = '';
            var zip = '';
            if (data.address) {
                var parts = data.address.split(',');
                var last = parts[parts.length - 1].trim().split(' ');
                zip = last[last.length - 1] || '';
            }
            resultCall.innerHTML =
                '<div class="section-divider"><span>Follow up by phone</span></div>' +
                '<p class="card-desc" style="margin:0.5rem 0;">A phone call takes 2 minutes and is the most effective way to be heard.</p>' +
                '<div class="call-script-text"><p>"Hello, my name is <strong>' + escHtml($('first_name').value || '___') + ' ' + escHtml($('last_name').value || '___') + '</strong>. I am a constituent from ZIP code <strong>' + zip + '</strong>. I submitted a comment and wanted to follow up. Please ensure my position is registered."</p></div>' +
                '<div class="call-numbers" style="margin-top:0.5rem;">' + callScriptData.map(function(r) { return '<p><strong>' + escHtml(r.name) + ':</strong> ' + escHtml(r.phone) + '</p>'; }).join('') + '</div>';
        }

        if (data.warnings && data.warnings.length) {
            resultWarnings.innerHTML = data.warnings.map(function(w) { return '<p>' + escHtml(w) + '</p>'; }).join('');
        }

        btnNewMessage.style.display = 'inline-flex';
    }

    btnNewMessage.addEventListener('click', function() {
        [pageResults, pageAddress].forEach(function(s) { s.style.display = 'none'; });
        pageMessage.style.display = '';
        confirmArea.style.display = 'none';
        captchaArea.style.display = 'none';
        callSection.style.display = 'none';
        autocompleteList.innerHTML = '';
        autocompleteList.style.display = 'none';
        captchaTokens = {};
        captchaWidgets = {};
        previewData = null;
        callScriptData = null;
        btnSend.querySelector('.btn-label').textContent = 'Send my message';
        btnSend.disabled = false;
        btnSend.classList.remove('is-sending');
        btnSend.removeAttribute('data-mode');
        pageMessage.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });

    // ---- Helpers ----
    function shake(el) {
        el.style.borderColor = 'var(--red)';
        el.style.animation = 'none';
        el.offsetHeight;
        el.style.animation = 'shake 0.4s ease';
        setTimeout(function() { el.style.borderColor = ''; el.style.animation = ''; }, 500);
    }

    function escHtml(str) {
        var div = document.createElement('div');
        div.textContent = str || '';
        return div.innerHTML;
    }
})();
