/**
 * NYC Bridge — 3-page flow
 * Page 1: Message + Name + Email + Topic
 * Page 2: Address + Confirm officials + Send
 * Page 3: Delivery results
 */
(function() {
    'use strict';

    const $ = (id) => document.getElementById(id);

    // Pages
    const pageMessage = $('page-message');
    const pageAddress = $('page-address');
    const pageResults = $('page-results');

    // Page 1
    const messageEl = $('message');
    const charCount = $('char-count');
    const btnToAddress = $('btn-to-address');

    // Page 2
    const addressInput = $('address');
    const autocompleteList = $('autocomplete-list');
    const confirmArea = $('confirm-area');
    const confirmReps = $('confirm-reps');
    const callArea = $('call-area');
    const callScript = $('call-script');
    const addressForm = $('address-form');
    const btnSend = $('btn-send');
    const btnAddrBack = $('btn-addr-back');

    // Page 3
    const resultTitle = $('result-title');
    const resultSummary = $('result-summary');
    const resultList = $('result-list');
    const resultWarnings = $('result-warnings');
    const resultCall = $('result-call');
    const btnNewMessage = $('btn-new-message');

    // State
    let previewData = null;
    let autocompleteTimer = null;
    let callScriptData = [];

    // ---- Character counter ----
    messageEl.addEventListener('input', function() {
        var len = this.value.length;
        charCount.textContent = len + ' / 5000';
        charCount.style.color = len > 4500 ? 'var(--red-light)' : len > 4000 ? '#eab308' : '';
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
                    return '<div class="autocomplete-item" role="option">' + escHtml(s.address || s) + '</div>';
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
        btnSend.querySelector('.btn-label').textContent = 'Looking up...';
        btnSend.classList.add('is-sending');

        var fd = new FormData();
        fd.append('message', messageEl.value);
        fd.append('address', addr);
        fd.append('first_name', $('first_name').value.trim());
        fd.append('last_name', $('last_name').value.trim());
        fd.append('email', $('email').value.trim());
        fd.append('topic', $('topic').value);

        fetch('/api/preview', { method: 'POST', body: fd })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.error) {
                    btnSend.disabled = false;
                    btnSend.querySelector('.btn-label').textContent = 'Send my message';
                    btnSend.classList.remove('is-sending');
                    addressInput.style.borderColor = 'var(--red)';
                    alert(data.error);
                    setTimeout(function() { addressInput.style.borderColor = ''; }, 2000);
                    return;
                }
                previewData = data;
                renderConfirm(data);
                confirmArea.style.display = '';
                confirmArea.scrollIntoView({ behavior: 'smooth', block: 'start' });
                btnSend.querySelector('.btn-label').textContent = 'Confirm & send';
                btnSend.disabled = false;
                btnSend.classList.remove('is-sending');
                btnSend.setAttribute('data-mode', 'confirm');
            })
            .catch(function() {
                btnSend.disabled = false;
                btnSend.querySelector('.btn-label').textContent = 'Send my message';
                btnSend.classList.remove('is-sending');
                alert('Connection error. Please try again.');
            });
    });

    // Group officials by jurisdiction for display
    function groupOfficials(officials) {
        var groups = {
            'citywide': { label: 'Citywide Officials', officials: [] },
            'district': { label: 'Your District Representatives', officials: [] },
            'borough': { label: 'Your Borough Officials', officials: [] },
            'statewide': { label: 'New York State Officials', officials: [] },
        };
        officials.forEach(function(o) {
            var key = o.jurisdiction || 'district';
            if (groups[key]) {
                groups[key].officials.push(o);
            } else {
                // State legislative districts fall under 'district'
                if (!groups['district']) groups['district'] = { label: 'Your District Representatives', officials: [] };
                groups['district'].officials.push(o);
            }
        });
        return Object.values(groups).filter(function(g) { return g.officials.length > 0; });
    }

    function renderConfirm(data) {
        var officials = data.officials || [];
        var groups = groupOfficials(officials);

        confirmReps.innerHTML = groups.map(function(group) {
            var cards = group.officials.map(function(o) {
                var badge = o.contact_method === 'email'
                    ? '<span class="confirm-chamber chamber-email">Email</span>'
                    : '<span class="confirm-chamber chamber-form">Web Form</span>';
                var phone = o.phone ? ' <span class="confirm-phone">📞 ' + escHtml(o.phone) + '</span>' : '';
                return '<div class="confirm-rep">' +
                    badge +
                    '<div><strong>' + escHtml(o.title) + '</strong></div>' +
                    '<div class="confirm-name">' + escHtml(o.name) +
                    (o.party ? ' <span class="confirm-party">(' + o.party + ')</span>' : '') +
                    phone + '</div>' +
                    (o.note ? '<div class="confirm-note" style="font-size:0.8rem;color:var(--white-muted);margin-top:0.25rem;">' + escHtml(o.note) + '</div>' : '') +
                    '</div>';
            }).join('');
            return '<div class="official-group"><h3 class="group-label">' + group.label + '</h3>' + cards + '</div>';
        }).join('');

        // Build call script
        var zip = '';
        if (data.address) {
            var parts = data.address.split(',');
            var last = parts[parts.length - 1].trim().split(' ');
            zip = last[last.length - 1] || '';
        }
        callScriptData = officials.filter(function(o) { return o.phone; }).map(function(o) {
            return { name: o.name + ' (' + o.title + ')', phone: o.phone };
        });

        if (callScriptData.length > 0) {
            callScript.innerHTML =
                '<p class="call-script-intro">A phone call is the most effective way to follow up:</p>' +
                '<div class="call-script-text"><p>"Hello, my name is <strong>' + escHtml($('first_name').value || '___') + ' ' + escHtml($('last_name').value || '___') + '</strong>. I am a constituent from ZIP code <strong>' + zip + '</strong>. I submitted a message about <strong>' + escHtml($('topic').value) + '</strong> and wanted to follow up. Please ensure my position is registered."</p></div>' +
                '<div class="call-numbers">' + callScriptData.map(function(r) { return '<p><strong>' + escHtml(r.name) + ':</strong> ' + escHtml(r.phone) + '</p>'; }).join('') + '</div>';
            callArea.style.display = '';
        } else {
            callArea.style.display = 'none';
        }
    }

    // ---- Confirm → Send ----
    btnSend.addEventListener('click', function() {
        if (btnSend.getAttribute('data-mode') !== 'confirm') return;

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

        fetch('/api/send', { method: 'POST', body: fd })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                renderResults(data);
                goTo(pageAddress, pageResults);
            })
            .catch(function() {
                alert('Connection error. Please try again.');
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
        var officials = data.officials || [];
        var summary = data.summary || {};
        var sent = summary.sent || 0;
        var total = summary.total || officials.length;
        var failed = summary.failed || 0;
        var manual = summary.manual_redirect || 0;

        if (sent === total) {
            resultTitle.textContent = 'Message sent to all ' + total + ' officials!';
        } else if (sent > 0) {
            resultTitle.textContent = 'Sent to ' + sent + ' of ' + total + ' officials';
        } else if (failed > 0) {
            resultTitle.textContent = 'Delivery could not be completed';
        } else {
            resultTitle.textContent = 'Delivery results';
        }

        var summaryParts = [];
        if (sent > 0) summaryParts.push(sent + ' sent');
        if (failed > 0) summaryParts.push(failed + ' failed');
        if (manual > 0) summaryParts.push(manual + ' need manual follow-up');
        resultSummary.innerHTML = summaryParts.length > 0
            ? '<p class="result-summary-text">' + summaryParts.join(' · ') + '</p>'
            : '';

        var icons = { sent: '✓', delivered: '✓', failed: '✗', skipped: '⊘', manual_redirect: '🔗' };

        resultList.innerHTML = officials.map(function(r) {
            return '<div class="result-item">' +
                '<div class="result-icon ' + r.status + '">' + (icons[r.status] || '?') + '</div>' +
                '<div class="result-body">' +
                '<div class="result-name">' + escHtml(r.title) + ' — ' + escHtml(r.name) + '</div>' +
                '<div class="result-detail">' + escHtml(r.detail || r.error || '') + '</div>' +
                (r.email_sent_to ? '<div class="result-email-sent" style="font-size:0.75rem;color:var(--white-muted);">To: ' + escHtml(r.email_sent_to) + '</div>' : '') +
                '</div>' +
                '<span class="result-method">' + (r.contact_method === 'email' ? 'email' : r.contact_method === 'form' ? 'form' : r.contact_method === 'email_fallback' ? 'email' : '') + '</span>' +
                '</div>';
        }).join('');

        // Call follow-up
        if (callScriptData.length > 0) {
            resultCall.style.display = '';
            var zip = '';
            if (data.address) {
                var parts = data.address.split(',');
                var last = parts[parts.length - 1].trim().split(' ');
                zip = last[last.length - 1] || '';
            }
            resultCall.innerHTML =
                '<div class="section-divider"><span>Follow up by phone</span></div>' +
                '<p class="card-desc" style="margin:0.5rem 0;">A phone call is the most effective way to follow up.</p>' +
                '<div class="call-script-text"><p>"Hello, my name is <strong>' + escHtml($('first_name').value || '___') + ' ' + escHtml($('last_name').value || '___') + '</strong>. I am a constituent from ZIP code <strong>' + zip + '</strong>. I submitted a message about <strong>' + escHtml($('topic').value) + '</strong> and wanted to follow up."</p></div>' +
                '<div class="call-numbers" style="margin-top:0.5rem;">' + callScriptData.map(function(r) { return '<p><strong>' + escHtml(r.name) + ':</strong> ' + escHtml(r.phone) + '</p>'; }).join('') + '</div>';
        }

        if (data.error) {
            resultWarnings.innerHTML = '<p style="color:var(--red-light);">' + escHtml(data.error) + '</p>';
        }

        btnNewMessage.style.display = 'inline-flex';
    }

    btnNewMessage.addEventListener('click', function() {
        [pageResults, pageAddress].forEach(function(s) { s.style.display = 'none'; });
        pageMessage.style.display = '';
        confirmArea.style.display = 'none';
        callArea.style.display = 'none';
        autocompleteList.innerHTML = '';
        autocompleteList.style.display = 'none';
        previewData = null;
        callScriptData = [];
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
