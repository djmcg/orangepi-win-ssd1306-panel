/* OLED page - interactive dashboard & agent console for /oled/ */
(function () {
    'use strict';

    var STATUS_URL = '/oled/oled-status.json';
    var API_STATUS_URL = '/api/status';
    var API_COMMAND_URL = '/api/command';
    var API_HISTORY_URL = '/api/history';
    var FRAME_URL = '/oled/oled-frame.png';
    var STALE_AFTER_MS = 15000;

    var selectedLines = 'auto';

    function setText(id, value) {
        var el = document.getElementById(id);
        if (!el) return;
        el.textContent = (value === undefined || value === null || value === '')
            ? '--' : value;
    }

    function refreshFrame() {
        var img = document.getElementById('frame');
        if (img) {
            img.src = FRAME_URL + '?t=' + Date.now();
        }
    }

    function renderRows(rows) {
        var table = document.getElementById('rows');
        if (!rows || !rows.length) {
            table.innerHTML = '<tr><td colspan="2">no data</td></tr>';
            return;
        }
        table.innerHTML = rows.map(function (row, index) {
            return '<tr><td>line ' + (index + 1) + '</td><td>'
                + String(row).replace(/</g, '&lt;') + '</td></tr>';
        }).join('');
    }

    function renderHistory(history) {
        var container = document.getElementById('historyList');
        if (!history || !history.length) {
            container.innerHTML = '<div style="color: #94a3b8; font-size: 0.9rem; text-align: center; padding: 12px;">No history entries yet</div>';
            return;
        }
        container.innerHTML = history.map(function (item) {
            var previewText = (item.rows || []).join(' | ');
            if (previewText.length > 50) {
                previewText = previewText.substring(0, 47) + '...';
            }
            return '<div class="history-item">' +
                '<div class="history-info">' +
                    '<div class="history-meta">' +
                        '<span>' + item.timestamp + '</span>' +
                        '<span>[' + item.mode + ']</span>' +
                    '</div>' +
                    '<div class="history-preview">' + escapeHtml(previewText) + '</div>' +
                '</div>' +
                '<button class="btn btn-secondary" style="padding: 6px 12px; font-size: 0.8rem;" onclick="restoreHistory(\'' + item.id + '\')">Restore</button>' +
            '</div>';
        }).join('');
    }

    function escapeHtml(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function apply(data) {
        var age = data.updated ? Date.now() - new Date(data.updated).getTime() : Infinity;
        var online = age < STALE_AFTER_MS;

        document.getElementById('dot').className = 'dot ' + (online ? 'online' : 'offline');
        setText('state', online ? 'online · ' + (data.board || '') : 'stale data');

        setText('bus', data.bus === undefined ? null : 'i2c-' + data.bus);
        setText('temp', (data.cpuTemp === null || data.cpuTemp === undefined)
            ? null : data.cpuTemp.toFixed(1) + ' °C');
        setText('uptime', data.uptime);
        setText('mode', data.mode);
        setText('board', data.board);
        setText('panel', data.panel ? data.panel + ' px' : null);
        setText('address', data.address);
        setText('datetime', data.datetime);
        setText('service', data.service);
        setText('updated', data.updated ? data.updated.replace('T', ' ') : null);
        setText('pid', data.pid);

        if (data.panel) {
            var parts = data.panel.split('x').map(Number);
            var scale = Math.max(1, Math.round(512 / parts[0]));
            var img = document.getElementById('frame');
            if (img) {
                img.style.width = (parts[0] * scale) + 'px';
                img.style.height = (parts[1] * scale) + 'px';
            }
        }

        renderRows(data.rows);
    }

    function fail() {
        document.getElementById('dot').className = 'dot offline';
        setText('state', 'no data — service inactive?');
        renderRows(null);
    }

    function loadStatus() {
        fetch(API_STATUS_URL + '?t=' + Date.now(), { cache: 'no-store' })
            .then(function (response) {
                if (!response.ok) throw new Error('HTTP ' + response.status);
                return response.json();
            })
            .then(apply)
            .catch(function() {
                // Fallback to static status json
                fetch(STATUS_URL + '?t=' + Date.now(), { cache: 'no-store' })
                    .then(function(res) { return res.json(); })
                    .then(apply)
                    .catch(fail);
            });
    }

    function loadHistory() {
        fetch(API_HISTORY_URL + '?t=' + Date.now(), { cache: 'no-store' })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                if (data && data.history) {
                    renderHistory(data.history);
                }
            })
            .catch(function () {});
    }

    function sendCommand(text, lines) {
        fetch(API_COMMAND_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ input: text, lines_count: lines })
        })
        .then(function (res) { return res.json(); })
        .then(function (data) {
            if (data && data.success) {
                loadStatus();
                loadHistory();
                setTimeout(refreshFrame, 200);
            }
        })
        .catch(function (err) {
            console.error('Command failed:', err);
        });
    }

    window.restoreHistory = function (id) {
        fetch('/api/history/restore/' + id, { method: 'POST' })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                if (data && data.success) {
                    loadStatus();
                    loadHistory();
                    setTimeout(refreshFrame, 200);
                }
            })
            .catch(function (err) {
                console.error('Restore failed:', err);
            });
    };

    // Event listeners setup
    document.addEventListener('DOMContentLoaded', function () {
        // Pill buttons for lines count
        var pills = document.querySelectorAll('.pill');
        pills.forEach(function (pill) {
            pill.addEventListener('click', function () {
                pills.forEach(function (p) { p.classList.remove('active'); });
                pill.classList.add('active');
                selectedLines = pill.getAttribute('data-lines');
                if (selectedLines !== 'auto') {
                    selectedLines = isNaN(selectedLines) ? selectedLines : Number(selectedLines);
                }
            });
        });

        // Send button
        var sendBtn = document.getElementById('sendBtn');
        var commandInput = document.getElementById('commandInput');

        function handleSend() {
            var val = commandInput.value.trim();
            if (!val) return;
            sendCommand(val, selectedLines);
            commandInput.value = '';
        }

        if (sendBtn) sendBtn.addEventListener('click', handleSend);
        if (commandInput) {
            commandInput.addEventListener('keypress', function (e) {
                if (e.key === 'Enter') {
                    handleSend();
                }
            });
        }

        // Quick action buttons
        var resetBtn = document.getElementById('resetBtn');
        if (resetBtn) {
            resetBtn.addEventListener('click', function () {
                sendCommand('default', 'auto');
            });
        }

        var tempBtn = document.getElementById('tempBtn');
        if (tempBtn) {
            tempBtn.addEventListener('click', function () {
                sendCommand('temp', 'auto');
            });
        }

        var clockBtn = document.getElementById('clockBtn');
        if (clockBtn) {
            clockBtn.addEventListener('click', function () {
                sendCommand('clock', 'auto');
            });
        }

        var demoBtn = document.getElementById('demoBtn');
        if (demoBtn) {
            demoBtn.addEventListener('click', function () {
                sendCommand('demo', 'auto');
            });
        }

        var fillMaxBtn = document.getElementById('fillMaxBtn');
        if (fillMaxBtn) {
            fillMaxBtn.addEventListener('click', function () {
                sendCommand('fill_max', 'auto');
            });
        }

        // Image upload handling
        var uploadBtn = document.getElementById('uploadBtn');
        var imageInput = document.getElementById('imageInput');
        var uploadStatus = document.getElementById('uploadStatus');

        if (uploadBtn && imageInput) {
            uploadBtn.addEventListener('click', function () {
                imageInput.click();
            });

            imageInput.addEventListener('change', function (e) {
                var file = e.target.files[0];
                if (!file) return;

                uploadStatus.textContent = 'Processing...';
                
                var formData = new FormData();
                formData.append('image', file);

                fetch('/api/upload-image', {
                    method: 'POST',
                    body: formData
                })
                .then(function (res) { return res.json(); })
                .then(function (data) {
                    if (data && data.success) {
                        uploadStatus.textContent = 'Image loaded';
                        loadStatus();
                        loadHistory();
                        setTimeout(refreshFrame, 200);
                    } else {
                        uploadStatus.textContent = 'Error: ' + (data.error || 'unknown');
                    }
                })
                .catch(function (err) {
                    console.error('Upload failed:', err);
                    uploadStatus.textContent = 'Upload failed';
                })
                .finally(function () {
                    imageInput.value = '';
                    setTimeout(function () { uploadStatus.textContent = ''; }, 3000);
                });
            });
        }
    });

    document.getElementById('frame').addEventListener('error', function () {
        document.getElementById('dot').className = 'dot offline';
        setText('state', 'no frame snapshot');
    });

    loadStatus();
    loadHistory();
    refreshFrame();
    setInterval(loadStatus, 2000);
    setInterval(loadHistory, 4000);
    setInterval(refreshFrame, 2000);
})();
