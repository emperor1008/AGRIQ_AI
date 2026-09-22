/**
 * Phase 1 — My Farm Data forms.
 * Wires the profile/farm/field/soil/cycle/observation forms to the
 * ownership-checked farmer-data API using the shared CSRF token from the
 * page. Feedback is farmer-friendly; technical errors are never shown.
 */
(function () {
    'use strict';

    var CSRF = '';
    var csrfMeta = document.querySelector('input[name="csrf_token"]');
    if (csrfMeta) CSRF = csrfMeta.value;

    function feedback(form, message, ok) {
        var el = form.querySelector('.form-feedback');
        if (!el) return;
        el.textContent = message;
        el.className = 'form-feedback ' + (ok ? 'ok' : 'error');
    }

    function send(url, method, body, isFormData, done) {
        var headers = { 'X-CSRF-Token': CSRF };
        var options = { method: method, headers: headers, credentials: 'same-origin' };
        if (body) options.body = body;
        if (!isFormData) headers['Content-Type'] = 'application/json';
        fetch(url, options)
            .then(function (response) {
                return response.json().then(function (payload) {
                    return { status: response.status, payload: payload };
                });
            })
            .then(function (result) {
                done(result);
            })
            .catch(function () {
                done({ status: 0, payload: { message: 'Network problem. Please try again.' } });
            });
    }

    function serialize(form) {
        var data = {};
        new FormData(form).forEach(function (value, key) {
            if (key === 'csrf_token') return;
            if (value instanceof File && !value.name) return;
            data[key] = typeof value === 'string' ? value.trim() : value;
        });
        return data;
    }

    function refreshContext() {
        fetch('/api/farmer-context', { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (payload) {
                if (payload && payload.ok) {
                    // Phase 1 keeps it simple: reload so the server-rendered
                    // section shows the persisted values.
                    window.location.reload();
                }
            })
            .catch(function () { /* silent; next visit reloads */ });
    }

    function bindJsonForm(formId, url, method, successMessage) {
        var form = document.getElementById(formId);
        if (!form) return;
        form.addEventListener('submit', function (event) {
            event.preventDefault();
            var payload = serialize(form);
            send(url, method, JSON.stringify(payload), false, function (result) {
                if (result.status >= 200 && result.status < 300 && result.payload.ok) {
                    feedback(form, successMessage, true);
                    setTimeout(refreshContext, 600);
                } else {
                    feedback(form, friendlyError(result), false);
                }
            });
        });
    }

    function friendlyError(result) {
        var message = result.payload && (result.payload.message || result.payload.error);
        if (result.status === 0) return message || 'Network problem. Please try again.';
        if (result.status === 401) return 'Please sign in again to continue.';
        if (result.status === 403) return 'You do not have access to this record.';
        if (result.status === 429) return 'Too many requests. Please wait a moment.';
        return message || 'Saved information could not be processed. Please check the values.';
    }

    // Profile: create or update depending on current state.
    var profileForm = document.getElementById('profileForm');
    if (profileForm) {
        profileForm.addEventListener('submit', function (event) {
            event.preventDefault();
            var payload = serialize(profileForm);
            var hasProfile = document.querySelector('[data-panel="profile"] p b');
            var method = hasProfile ? 'PATCH' : 'POST';
            send('/api/profile', method, JSON.stringify(payload), false, function (result) {
                if (result.status >= 200 && result.status < 300 && result.payload.ok) {
                    feedback(profileForm, 'Profile saved.', true);
                    setTimeout(refreshContext, 600);
                } else {
                    feedback(profileForm, friendlyError(result), false);
                }
            });
        });
    }

    bindJsonForm('farmForm', '/api/farms', 'POST', 'Farm registered.');

    // Field creation needs the farm id from the loaded context.
    var fieldForm = document.getElementById('fieldForm');
    if (fieldForm) {
        fieldForm.addEventListener('submit', function (event) {
            event.preventDefault();
            fetch('/api/farms', { credentials: 'same-origin' })
                .then(function (r) { return r.json(); })
                .then(function (payload) {
                    if (!payload.ok || !payload.farms || !payload.farms.length) {
                        feedback(fieldForm, 'Register your farm first, then add fields.', false);
                        return;
                    }
                    var farmId = payload.farms[0].id;
                    send('/api/farms/' + farmId + '/fields', 'POST',
                        JSON.stringify(serialize(fieldForm)), false, function (result) {
                            if (result.status >= 200 && result.status < 300 && result.payload.ok) {
                                feedback(fieldForm, 'Field added.', true);
                                setTimeout(refreshContext, 600);
                            } else {
                                feedback(fieldForm, friendlyError(result), false);
                            }
                        });
                })
                .catch(function () {
                    feedback(fieldForm, 'Network problem. Please try again.', false);
                });
        });
    }

    // Soil: multipart (optional document upload).
    var soilForm = document.getElementById('soilForm');
    if (soilForm) {
        soilForm.addEventListener('submit', function (event) {
            event.preventDefault();
            // Resolve field id through the context endpoint.
            fetch('/api/farmer-context', { credentials: 'same-origin' })
                .then(function (r) { return r.json(); })
                .then(function (payload) {
                    var field = payload && payload.context && payload.context.field;
                    if (!field || !field.id) {
                        feedback(soilForm, 'Add a field first, then save soil information.', false);
                        return null;
                    }
                    var data = new FormData(soilForm);
                    return { fieldId: field.id, data: data };
                })
                .then(function (prepared) {
                    if (!prepared) return;
                    send('/api/fields/' + prepared.fieldId + '/soil-tests', 'POST',
                        prepared.data, true, function (result) {
                            if (result.status >= 200 && result.status < 300 && result.payload.ok) {
                                feedback(soilForm, 'Soil record saved. Unknown values stay unknown.', true);
                                setTimeout(refreshContext, 600);
                            } else {
                                feedback(soilForm, friendlyError(result), false);
                            }
                        });
                })
                .catch(function () {
                    feedback(soilForm, 'Network problem. Please try again.', false);
                });
        });
    }

    // Crop cycle creation + stage confirmation.
    var cycleForm = document.getElementById('cycleForm');
    if (cycleForm) {
        cycleForm.addEventListener('submit', function (event) {
            event.preventDefault();
            fetch('/api/farmer-context', { credentials: 'same-origin' })
                .then(function (r) { return r.json(); })
                .then(function (payload) {
                    var field = payload && payload.context && payload.context.field;
                    if (!field || !field.id) {
                        feedback(cycleForm, 'Add a field first, then start a crop cycle.', false);
                        return null;
                    }
                    return { fieldId: field.id };
                })
                .then(function (prepared) {
                    if (!prepared) return;
                    send('/api/fields/' + prepared.fieldId + '/crop-cycles', 'POST',
                        JSON.stringify(serialize(cycleForm)), false, function (result) {
                            if (result.status >= 200 && result.status < 300 && result.payload.ok) {
                                feedback(cycleForm, 'Crop cycle started. Confirm the stage below.', true);
                                setTimeout(refreshContext, 600);
                            } else {
                                feedback(cycleForm, friendlyError(result), false);
                            }
                        });
                })
                .catch(function () {
                    feedback(cycleForm, 'Network problem. Please try again.', false);
                });
        });
    }

    var stageForm = document.getElementById('stageForm');
    if (stageForm) {
        stageForm.addEventListener('submit', function (event) {
            event.preventDefault();
            var cycleId = stageForm.getAttribute('data-cycle-id');
            if (!cycleId) {
                // Pull from context when not stamped server-side.
                fetch('/api/farmer-context', { credentials: 'same-origin' })
                    .then(function (r) { return r.json(); })
                    .then(function (payload) {
                        var cycle = payload && payload.context && payload.context.crop_cycle;
                        if (!cycle || !cycle.id) return;
                        return sendConfirm(cycle.id);
                    })
                    .catch(function () { });
            } else {
                sendConfirm(cycleId);
            }
        });
    }

    function sendConfirm(cycleId) {
        send('/api/crop-cycles/' + cycleId + '/confirm-stage', 'POST',
            JSON.stringify({ stage: stageForm.querySelector('select[name="stage"]').value }),
            false, function (result) {
                if (result.status >= 200 && result.status < 300 && result.payload.ok) {
                    feedback(stageForm, 'Stage confirmed. Thank you.', true);
                    setTimeout(refreshContext, 600);
                } else {
                    feedback(stageForm, friendlyError(result), false);
                }
            });
    }

    // Observation: multipart with optional photo.
    var observationForm = document.getElementById('observationForm');
    if (observationForm) {
        observationForm.addEventListener('submit', function (event) {
            event.preventDefault();
            fetch('/api/farmer-context', { credentials: 'same-origin' })
                .then(function (r) { return r.json(); })
                .then(function (payload) {
                    var cycle = payload && payload.context && payload.context.crop_cycle;
                    if (!cycle || !cycle.id) {
                        feedback(observationForm, 'Start a crop cycle first.', false);
                        return null;
                    }
                    return { cycleId: cycle.id };
                })
                .then(function (prepared) {
                    if (!prepared) return;
                    send('/api/crop-cycles/' + prepared.cycleId + '/observations', 'POST',
                        new FormData(observationForm), true, function (result) {
                            if (result.status >= 200 && result.status < 300 && result.payload.ok) {
                                feedback(observationForm, 'Observation saved to the field timeline.', true);
                                setTimeout(refreshContext, 600);
                            } else {
                                feedback(observationForm, friendlyError(result), false);
                            }
                        });
                })
                .catch(function () {
                    feedback(observationForm, 'Network problem. Please try again.', false);
                });
        });
    }

    // Stamp the active cycle id for stage confirmation when known server-side.
    var activeCyclePanel = document.querySelector('[data-panel="cycle"]');
    if (activeCyclePanel && stageForm) {
        fetch('/api/farmer-context', { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (payload) {
                var cycle = payload && payload.context && payload.context.crop_cycle;
                if (cycle && cycle.id) stageForm.setAttribute('data-cycle-id', String(cycle.id));
            })
            .catch(function () { });
    }
})();
