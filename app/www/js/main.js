let bootData = null;
let bootOrderList = [];
let originalBootOrder = [];
let disksData = null;
let pendingDeleteId = null;
let pendingRestoreFile = null;
let editDisksData = null;

const API_BASE = './api';

function initTheme() {
    function applyTheme(theme) {
        if (theme === 'dark') {
            document.documentElement.setAttribute('data-theme', 'dark');
        } else if (theme === 'light') {
            document.documentElement.setAttribute('data-theme', 'light');
        } else {
            document.documentElement.removeAttribute('data-theme');
        }
    }

    function getFnosTheme() {
        var modeCode = localStorage.getItem('fnos-theme-mode');
        if (modeCode === '20') return 'dark';
        if (modeCode === '10') return 'light';
        return null;
    }

    var fnosTheme = getFnosTheme();
    if (fnosTheme) {
        applyTheme(fnosTheme);
    } else {
        applyTheme('auto');
    }

    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function() {
        var current = getFnosTheme();
        if (!current) {
            applyTheme('auto');
        }
    });

    window.addEventListener('storage', function(e) {
        if (e.key === 'fnos-theme-mode') {
            var theme = getFnosTheme();
            if (theme) {
                applyTheme(theme);
            } else {
                applyTheme('auto');
            }
        }
    });

    try {
        if (window.parent && window.parent !== window) {
            window.parent.postMessage({ type: 'fnos-theme-request' }, '*');

            window.addEventListener('message', function(event) {
                if (event.data && event.data.type === 'fnos-theme') {
                    var theme = event.data.theme;
                    if (theme === 'dark' || theme === 'light') {
                        applyTheme(theme);
                    }
                }
                if (event.data && event.data.type === 'fnos-theme-change') {
                    var newTheme = event.data.theme;
                    if (newTheme === 'dark' || newTheme === 'light') {
                        applyTheme(newTheme);
                    }
                }
            });
        }
    } catch (e) {}
}

initTheme();

function showToast(message, type) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = 'toast toast-' + (type || 'info');
    toast.style.display = 'block';
    clearTimeout(toast._timer);
    toast._timer = setTimeout(function() {
        toast.style.display = 'none';
    }, 3000);
}

function getEntryName(id) {
    if (!bootData || !bootData.entries) return 'Unknown';
    var entry = bootData.entries.find(function(e) { return e.id === id; });
    return entry ? entry.name : 'Unknown (' + id + ')';
}

function getEntryById(id) {
    if (!bootData || !bootData.entries) return null;
    return bootData.entries.find(function(e) { return e.id === id; });
}

function renderStatus() {
    var bootCurrentEl = document.getElementById('bootCurrent');
    var bootNextEl = document.getElementById('bootNext');
    var bootOrderEl = document.getElementById('bootOrderDisplay');

    if (bootData.boot_current) {
        var name = getEntryName(bootData.boot_current);
        bootCurrentEl.textContent = 'Boot' + bootData.boot_current + ' - ' + name;
    } else {
        bootCurrentEl.textContent = '未知';
    }

    if (bootData.boot_next) {
        var nextName = getEntryName(bootData.boot_next);
        bootNextEl.textContent = 'Boot' + bootData.boot_next + ' - ' + nextName;
        document.getElementById('clearBootNextBtn').style.display = '';
    } else {
        bootNextEl.textContent = '未设置';
        document.getElementById('clearBootNextBtn').style.display = 'none';
    }

    if (bootData.boot_order && bootData.boot_order.length > 0) {
        bootOrderEl.textContent = bootData.boot_order.map(function(id) {
            return 'Boot' + id;
        }).join(' \u2192 ');
    } else {
        bootOrderEl.textContent = '未知';
    }
}

function renderEntries(resetOrder) {
    var tbody = document.getElementById('entriesBody');
    tbody.innerHTML = '';

    if (!bootData.entries || bootData.entries.length === 0) {
        var tr = document.createElement('tr');
        tr.innerHTML = '<td colspan="5" class="empty-cell">未找到启动项</td>';
        tbody.appendChild(tr);
        return;
    }

    if (resetOrder !== false) {
        bootOrderList = bootData.boot_order ? bootData.boot_order.slice() : [];
        originalBootOrder = bootData.boot_order ? bootData.boot_order.slice() : [];
    }

    var entryMap = {};
    bootData.entries.forEach(function(entry) {
        entryMap[entry.id] = entry;
    });

    var renderedIds = {};
    bootOrderList.forEach(function(bootId, index) {
        var entry = entryMap[bootId];
        if (!entry) return;
        renderedIds[bootId] = true;
        renderEntryRow(tbody, entry, index);
    });

    var hasUnordered = false;
    bootData.entries.forEach(function(entry) {
        if (!renderedIds[entry.id]) {
            if (!hasUnordered) {
                hasUnordered = true;
                var sepTr = document.createElement('tr');
                sepTr.innerHTML = '<td colspan="5" class="separator-cell">未在启动顺序中的条目</td>';
                tbody.appendChild(sepTr);
            }
            renderEntryRow(tbody, entry, -1);
        }
    });

    updateSaveOrderBtn();
}

function renderEntryRow(tbody, entry, orderIndex) {
    var tr = document.createElement('tr');
    if (entry.id === bootData.boot_current) tr.className += ' row-current';
    if (entry.id === bootData.boot_next) tr.className += ' row-next';

    var statusTags = [];
    if (entry.id === bootData.boot_current) statusTags.push('current');
    if (entry.id === bootData.boot_next) statusTags.push('next');
    if (entry.active) statusTags.push('active');
    else statusTags.push('inactive');

    var statusHtml = statusTags.map(function(t) {
        var labels = {
            current: '当前启动',
            next: '下次启动',
            active: '活跃',
            inactive: '禁用'
        };
        return '<span class="tag tag-' + t + '">' + labels[t] + '</span>';
    }).join(' ');

    var orderHtml;
    if (orderIndex >= 0) {
        var canUp = orderIndex > 0;
        var canDown = orderIndex < bootOrderList.length - 1;
        orderHtml =
            '<div class="order-cell">' +
                '<span class="order-num">' + (orderIndex + 1) + '</span>' +
                '<button class="btn btn-icon-only btn-order" onclick="moveUp(' + orderIndex + ')" ' + (canUp ? '' : 'disabled') + ' title="上移">&#9650;</button>' +
                '<button class="btn btn-icon-only btn-order" onclick="moveDown(' + orderIndex + ')" ' + (canDown ? '' : 'disabled') + ' title="下移">&#9660;</button>' +
            '</div>';
    } else {
        orderHtml = '<div class="order-cell"><span class="order-num order-unordered">--</span></div>';
    }

    var isCurrentNext = entry.id === bootData.boot_next;
    var nextBtnClass = isCurrentNext ? 'btn btn-xs btn-disabled' : 'btn btn-xs btn-primary';
    var nextBtnText = isCurrentNext ? '已设为下次' : '下次启动';
    var nextBtnDisabled = isCurrentNext ? 'disabled' : '';
    var nextBtnOnclick = isCurrentNext ? '' : 'onclick="setBootNext(\'' + entry.id + '\')"';

    var toggleBtnClass, toggleBtnText, toggleBtnOnclick;
    if (entry.active) {
        toggleBtnClass = 'btn btn-xs btn-outline-warning';
        toggleBtnText = '禁用';
        toggleBtnOnclick = 'onclick="toggleActive(\'' + entry.id + '\', false)"';
    } else {
        toggleBtnClass = 'btn btn-xs btn-outline-success';
        toggleBtnText = '激活';
        toggleBtnOnclick = 'onclick="toggleActive(\'' + entry.id + '\', true)"';
    }

    var editBtnHtml = '<button class="btn btn-xs btn-outline-primary" onclick="openEditModal(\'' + entry.id + '\')">编辑</button>';
    var deleteBtnHtml = '<button class="btn btn-xs btn-outline-danger" onclick="openDeleteModal(\'' + entry.id + '\')">删除</button>';

    tr.innerHTML =
        '<td class="col-order">' + orderHtml + '</td>' +
        '<td class="col-id">Boot' + entry.id + '</td>' +
        '<td class="col-name" title="' + escapeHtml(entry.name) + '">' + escapeHtml(entry.name) + '</td>' +
        '<td class="col-status">' + statusHtml + '</td>' +
        '<td class="col-action">' +
            '<div class="action-group">' +
                '<button class="' + nextBtnClass + '" ' + nextBtnDisabled + ' ' + nextBtnOnclick + '>' + nextBtnText + '</button>' +
                '<button class="' + toggleBtnClass + '" ' + toggleBtnOnclick + '>' + toggleBtnText + '</button>' +
                editBtnHtml +
                deleteBtnHtml +
            '</div>' +
        '</td>';

    tbody.appendChild(tr);
}

function updateSaveOrderBtn() {
    var btn = document.getElementById('saveOrderBtn');
    if (!btn) return;
    var changed = bootOrderList.length !== originalBootOrder.length;
    if (!changed) {
        for (var i = 0; i < bootOrderList.length; i++) {
            if (bootOrderList[i] !== originalBootOrder[i]) {
                changed = true;
                break;
            }
        }
    }
    btn.style.display = changed ? '' : 'none';
}

function escapeHtml(text) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(text));
    return div.innerHTML;
}

function loadEntries() {
    var tbody = document.getElementById('entriesBody');
    tbody.innerHTML = '<tr><td colspan="5" class="loading-cell">加载中...</td></tr>';

    fetch(API_BASE + '/entries')
        .then(function(response) { return response.json(); })
        .then(function(result) {
            if (result.success) {
                bootData = result.data;
                renderStatus();
                renderEntries();
            } else {
                showToast(result.message || '加载失败', 'error');
                document.getElementById('bootCurrent').textContent = '加载失败';
                document.getElementById('bootNext').textContent = '加载失败';
                document.getElementById('bootOrderDisplay').textContent = '加载失败';
                tbody.innerHTML = '<tr><td colspan="5" class="error-cell">' + escapeHtml(result.message || '加载失败') + '</td></tr>';
            }
        })
        .catch(function(error) {
            showToast('网络错误: ' + error.message, 'error');
            document.getElementById('bootCurrent').textContent = '网络错误';
            document.getElementById('bootNext').textContent = '网络错误';
            document.getElementById('bootOrderDisplay').textContent = '网络错误';
            tbody.innerHTML = '<tr><td colspan="5" class="error-cell">网络错误: ' + escapeHtml(error.message) + '</td></tr>';
        });
}

function setBootNext(bootId) {
    if (!confirm('确定将 Boot' + bootId + ' - ' + getEntryName(bootId) + ' 设为下次启动项吗？')) {
        return;
    }

    fetch(API_BASE + '/set_bootnext', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ boot_id: bootId })
    })
    .then(function(response) { return response.json(); })
    .then(function(result) {
        if (result.success) {
            showToast(result.message, 'success');
            loadEntries();
        } else {
            showToast(result.message || '设置失败', 'error');
        }
    })
    .catch(function(error) {
        showToast('设置失败: ' + error.message, 'error');
    });
}

function clearBootNext() {
    if (!confirm('确定要清除下次启动项设置吗？')) {
        return;
    }

    fetch(API_BASE + '/clear_bootnext', {
        method: 'POST'
    })
    .then(function(response) { return response.json(); })
    .then(function(result) {
        if (result.success) {
            showToast(result.message, 'success');
            loadEntries();
        } else {
            showToast(result.message || '清除失败', 'error');
        }
    })
    .catch(function(error) {
        showToast('清除失败: ' + error.message, 'error');
    });
}

function toggleActive(bootId, activate) {
    var action = activate ? '激活' : '禁用';
    var entryName = getEntryName(bootId);
    if (!confirm('确定要' + action + '启动项 Boot' + bootId + ' - ' + entryName + ' 吗？')) {
        return;
    }

    var endpoint = activate ? '/activate_entry' : '/deactivate_entry';

    fetch(API_BASE + endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ boot_id: bootId })
    })
    .then(function(response) { return response.json(); })
    .then(function(result) {
        if (result.success) {
            showToast(result.message, 'success');
            loadEntries();
        } else {
            showToast(result.message || action + '失败', 'error');
        }
    })
    .catch(function(error) {
        showToast(action + '失败: ' + error.message, 'error');
    });
}

function moveUp(index) {
    if (index <= 0) return;
    var temp = bootOrderList[index];
    bootOrderList[index] = bootOrderList[index - 1];
    bootOrderList[index - 1] = temp;
    renderEntries(false);
}

function moveDown(index) {
    if (index >= bootOrderList.length - 1) return;
    var temp = bootOrderList[index];
    bootOrderList[index] = bootOrderList[index + 1];
    bootOrderList[index + 1] = temp;
    renderEntries(false);
}

function saveBootOrder() {
    var newOrder = bootOrderList.join(',');
    if (!confirm('确定要保存新的启动顺序吗？\n\n新顺序: ' + bootOrderList.map(function(id) { return 'Boot' + id; }).join(' → '))) {
        return;
    }

    fetch(API_BASE + '/set_bootorder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ order: newOrder })
    })
    .then(function(response) { return response.json(); })
    .then(function(result) {
        if (result.success) {
            showToast(result.message, 'success');
            loadEntries();
        } else {
            showToast(result.message || '保存失败', 'error');
        }
    })
    .catch(function(error) {
        showToast('保存失败: ' + error.message, 'error');
    });
}

function loadDisks(mode) {
    var diskSelectId = mode === 'edit' ? 'editDisk' : 'entryDisk';
    var diskSelect = document.getElementById(diskSelectId);
    diskSelect.innerHTML = '<option value="">-- 加载中 --</option>';

    return fetch(API_BASE + '/disks')
        .then(function(response) { return response.json(); })
        .then(function(result) {
            if (result.success) {
                var data = result.data.disks;
                if (mode === 'edit') {
                    editDisksData = data;
                } else {
                    disksData = data;
                }
                diskSelect.innerHTML = '<option value="">-- 请选择磁盘 --</option>';
                data.forEach(function(disk) {
                    var opt = document.createElement('option');
                    opt.value = disk.name;
                    opt.textContent = disk.name + ' (' + disk.size + (disk.pttype ? ', ' + disk.pttype : '') + ')';
                    diskSelect.appendChild(opt);
                });
                return data;
            } else {
                diskSelect.innerHTML = '<option value="">-- 加载失败 --</option>';
                showToast(result.message || '加载磁盘信息失败', 'error');
                return null;
            }
        })
        .catch(function(error) {
            diskSelect.innerHTML = '<option value="">-- 加载失败 --</option>';
            showToast('加载磁盘信息失败: ' + error.message, 'error');
            return null;
        });
}

function onDiskChange(mode) {
    var diskSelectId, partitionSelectId, data;

    if (mode === 'edit') {
        diskSelectId = 'editDisk';
        partitionSelectId = 'editPartition';
        data = editDisksData;
    } else {
        diskSelectId = 'entryDisk';
        partitionSelectId = 'entryPartition';
        data = disksData;
    }

    var diskSelect = document.getElementById(diskSelectId);
    var partitionSelect = document.getElementById(partitionSelectId);
    var selectedDisk = diskSelect.value;

    partitionSelect.innerHTML = '';

    if (!selectedDisk || !data) {
        partitionSelect.innerHTML = '<option value="">-- 请先选择磁盘 --</option>';
        return;
    }

    var disk = data.find(function(d) { return d.name === selectedDisk; });

    if (!disk || !disk.partitions || disk.partitions.length === 0) {
        partitionSelect.innerHTML = '<option value="">-- 无可用分区 --</option>';
        return;
    }

    partitionSelect.innerHTML = '<option value="">-- 请选择分区 --</option>';
    disk.partitions.forEach(function(part) {
        var opt = document.createElement('option');
        opt.value = part.number;
        var label = part.name + ' (' + part.size;
        if (part.fstype) label += ', ' + part.fstype;
        if (part.mountpoint) label += ', ' + part.mountpoint;
        label += ')';
        opt.textContent = label;
        partitionSelect.appendChild(opt);
    });
}

function openCreateModal() {
    document.getElementById('entryLabel').value = '';
    document.getElementById('entryLoader').value = '';
    document.getElementById('entryDisk').innerHTML = '<option value="">-- 加载中 --</option>';
    document.getElementById('entryPartition').innerHTML = '<option value="">-- 请先选择磁盘 --</option>';
    document.getElementById('createModal').style.display = 'flex';
    loadDisks('create');
}

function closeCreateModal() {
    document.getElementById('createModal').style.display = 'none';
}

function createEntry() {
    var label = document.getElementById('entryLabel').value.trim();
    var disk = document.getElementById('entryDisk').value;
    var partition = document.getElementById('entryPartition').value;
    var loader = document.getElementById('entryLoader').value.trim();

    if (!label) {
        showToast('请输入启动项名称', 'error');
        return;
    }
    if (!disk) {
        showToast('请选择磁盘设备', 'error');
        return;
    }
    if (!partition) {
        showToast('请选择分区编号', 'error');
        return;
    }
    if (!loader) {
        showToast('请输入EFI加载器路径', 'error');
        return;
    }

    var btn = document.getElementById('createEntryBtn');
    btn.disabled = true;
    btn.textContent = '创建中...';

    fetch(API_BASE + '/create_entry', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            label: label,
            disk: disk,
            partition: partition,
            loader: loader
        })
    })
    .then(function(response) { return response.json(); })
    .then(function(result) {
        btn.disabled = false;
        btn.textContent = '创建';
        if (result.success) {
            showToast(result.message, 'success');
            closeCreateModal();
            loadEntries();
        } else {
            showToast(result.message || '创建失败', 'error');
        }
    })
    .catch(function(error) {
        btn.disabled = false;
        btn.textContent = '创建';
        showToast('创建失败: ' + error.message, 'error');
    });
}

function openEditModal(bootId) {
    document.getElementById('editBootId').value = 'Boot' + bootId;
    document.getElementById('editLabel').value = '';
    document.getElementById('editLoader').value = '';
    document.getElementById('editDisk').innerHTML = '<option value="">-- 加载中 --</option>';
    document.getElementById('editPartition').innerHTML = '<option value="">-- 请先选择磁盘 --</option>';
    document.getElementById('editModal').style.display = 'flex';

    loadDisks('edit').then(function() {
        return fetch(API_BASE + '/entry_detail', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ boot_id: bootId })
        });
    })
    .then(function(response) { return response.json(); })
    .then(function(result) {
        if (result.success) {
            var detail = result.data;
            document.getElementById('editBootId').value = 'Boot' + detail.id;
            document.getElementById('editLabel').value = detail.name;
            document.getElementById('editLoader').value = detail.loader;

            if (detail.disk) {
                var diskSelect = document.getElementById('editDisk');
                var options = diskSelect.options;
                for (var i = 0; i < options.length; i++) {
                    if (options[i].value === detail.disk) {
                        options[i].selected = true;
                        onDiskChange('edit');
                        var partSelect = document.getElementById('editPartition');
                        var partOptions = partSelect.options;
                        for (var j = 0; j < partOptions.length; j++) {
                            if (partOptions[j].value === detail.partition) {
                                partOptions[j].selected = true;
                                break;
                            }
                        }
                        break;
                    }
                }
            }
        } else {
            showToast(result.message || '获取启动项详情失败', 'error');
        }
    })
    .catch(function(error) {
        showToast('获取详情失败: ' + error.message, 'error');
    });
}

function closeEditModal() {
    document.getElementById('editModal').style.display = 'none';
}

function updateEntry() {
    var bootIdText = document.getElementById('editBootId').value;
    var oldBootId = bootIdText.replace('Boot', '');
    var label = document.getElementById('editLabel').value.trim();
    var disk = document.getElementById('editDisk').value;
    var partition = document.getElementById('editPartition').value;
    var loader = document.getElementById('editLoader').value.trim();

    if (!label) {
        showToast('请输入启动项名称', 'error');
        return;
    }
    if (!disk) {
        showToast('请选择磁盘设备', 'error');
        return;
    }
    if (!partition) {
        showToast('请选择分区编号', 'error');
        return;
    }
    if (!loader) {
        showToast('请输入EFI加载器路径', 'error');
        return;
    }

    var btn = document.getElementById('updateEntryBtn');
    btn.disabled = true;
    btn.textContent = '保存中...';

    fetch(API_BASE + '/update_entry', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            old_boot_id: oldBootId,
            label: label,
            disk: disk,
            partition: partition,
            loader: loader
        })
    })
    .then(function(response) { return response.json(); })
    .then(function(result) {
        btn.disabled = false;
        btn.textContent = '保存修改';
        if (result.success) {
            showToast(result.message, 'success');
            closeEditModal();
            loadEntries();
        } else {
            showToast(result.message || '修改失败', 'error');
        }
    })
    .catch(function(error) {
        btn.disabled = false;
        btn.textContent = '保存修改';
        showToast('修改失败: ' + error.message, 'error');
    });
}

function openDeleteModal(bootId) {
    pendingDeleteId = bootId;
    var entryName = 'Boot' + bootId + ' - ' + getEntryName(bootId);
    document.getElementById('deleteEntryName').textContent = entryName;
    document.getElementById('deleteModal').style.display = 'flex';
}

function closeDeleteModal() {
    document.getElementById('deleteModal').style.display = 'none';
    pendingDeleteId = null;
}

function confirmDelete() {
    if (!pendingDeleteId) return;

    var btn = document.getElementById('confirmDeleteBtn');
    btn.disabled = true;
    btn.textContent = '删除中...';

    fetch(API_BASE + '/delete_entry', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ boot_id: pendingDeleteId })
    })
    .then(function(response) { return response.json(); })
    .then(function(result) {
        btn.disabled = false;
        btn.textContent = '确认删除';
        if (result.success) {
            showToast(result.message, 'success');
            closeDeleteModal();
            loadEntries();
        } else {
            showToast(result.message || '删除失败', 'error');
        }
    })
    .catch(function(error) {
        btn.disabled = false;
        btn.textContent = '确认删除';
        showToast('删除失败: ' + error.message, 'error');
    });
}

function loadBackups() {
    var backupList = document.getElementById('backupList');
    backupList.innerHTML = '<div class="backup-empty">加载中...</div>';

    fetch(API_BASE + '/list_backups')
        .then(function(response) { return response.json(); })
        .then(function(result) {
            if (result.success) {
                var backups = result.data.backups;
                if (!backups || backups.length === 0) {
                    backupList.innerHTML = '<div class="backup-empty">暂无备份</div>';
                    return;
                }

                backupList.innerHTML = '';
                backups.forEach(function(backup) {
                    var item = document.createElement('div');
                    item.className = 'backup-item';

                    var tsDisplay = '';
                    if (backup.timestamp) {
                        tsDisplay = backup.timestamp.replace(/(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/, '$1-$2-$3 $4:$5:$6');
                    }

                    item.innerHTML =
                        '<div class="backup-info">' +
                            '<div class="backup-name">' + escapeHtml(backup.filename) + '</div>' +
                            '<div class="backup-meta">' +
                                '<span class="backup-meta-item">时间: ' + tsDisplay + '</span>' +
                                '<span class="backup-meta-item">条目数: ' + backup.entry_count + '</span>' +
                                (backup.boot_order ? '<span class="backup-meta-item">启动顺序: ' + backup.boot_order + '</span>' : '') +
                            '</div>' +
                        '</div>' +
                        '<div class="backup-actions">' +
                            '<button class="btn btn-xs btn-outline-primary" onclick="openRestoreModal(\'' + escapeHtml(backup.filename) + '\')">恢复</button>' +
                            '<button class="btn btn-xs btn-outline-danger" onclick="deleteBackup(\'' + escapeHtml(backup.filename) + '\')">删除</button>' +
                        '</div>';

                    backupList.appendChild(item);
                });
            } else {
                backupList.innerHTML = '<div class="backup-empty">' + escapeHtml(result.message || '加载失败') + '</div>';
            }
        })
        .catch(function(error) {
            backupList.innerHTML = '<div class="backup-empty">加载失败</div>';
            showToast('加载备份列表失败: ' + error.message, 'error');
        });
}

function createBackup() {
    if (!confirm('确定要创建当前EFI启动配置的备份吗？')) {
        return;
    }

    fetch(API_BASE + '/backup', {
        method: 'POST'
    })
    .then(function(response) { return response.json(); })
    .then(function(result) {
        if (result.success) {
            showToast(result.message, 'success');
            loadBackups();
        } else {
            showToast(result.message || '备份失败', 'error');
        }
    })
    .catch(function(error) {
        showToast('备份失败: ' + error.message, 'error');
    });
}

function openRestoreModal(filename) {
    pendingRestoreFile = filename;
    document.getElementById('restoreFileName').textContent = filename;
    document.getElementById('restoreModal').style.display = 'flex';
}

function closeRestoreModal() {
    document.getElementById('restoreModal').style.display = 'none';
    pendingRestoreFile = null;
}

function confirmRestore() {
    if (!pendingRestoreFile) return;

    var btn = document.getElementById('confirmRestoreBtn');
    btn.disabled = true;
    btn.textContent = '恢复中...';

    fetch(API_BASE + '/restore_backup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: pendingRestoreFile })
    })
    .then(function(response) { return response.json(); })
    .then(function(result) {
        btn.disabled = false;
        btn.textContent = '确认恢复';
        if (result.success) {
            showToast(result.message, 'success');
            closeRestoreModal();
            loadEntries();
            loadBackups();
        } else {
            showToast(result.message || '恢复失败', 'error');
        }
    })
    .catch(function(error) {
        btn.disabled = false;
        btn.textContent = '确认恢复';
        showToast('恢复失败: ' + error.message, 'error');
    });
}

function deleteBackup(filename) {
    if (!confirm('确定要删除备份 ' + filename + ' 吗？')) {
        return;
    }

    fetch(API_BASE + '/delete_backup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: filename })
    })
    .then(function(response) { return response.json(); })
    .then(function(result) {
        if (result.success) {
            showToast(result.message, 'success');
            loadBackups();
        } else {
            showToast(result.message || '删除失败', 'error');
        }
    })
    .catch(function(error) {
        showToast('删除失败: ' + error.message, 'error');
    });
}

loadEntries();
loadBackups();
