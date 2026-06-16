/**
 * SLG 每日资讯 - 前端逻辑
 * 纯原生 JS（ES6+），无任何框架依赖
 */

(function () {
    'use strict';

    // ============================================
    // DOM 引用
    // ============================================
    const $sidebar       = document.getElementById('dateList');
    const $datePickerM   = document.getElementById('datePickerMobile');
    const $cardList      = document.getElementById('cardList');
    const $stateMessage  = document.getElementById('stateMessage');
    const $currentDate   = document.getElementById('currentDate');

    // 当前选中日期
    let currentDate = null;
    // 日期索引缓存
    let dateIndex = [];

    // ============================================
    // 工具函数
    // ============================================

    /** 显示状态信息（loading / error / empty） */
    function showState(text, isError = false) {
        $stateMessage.textContent = text;
        $stateMessage.classList.remove('hidden', 'error');
        if (isError) $stateMessage.classList.add('error');
        $cardList.innerHTML = '';
    }

    /** 隐藏状态信息 */
    function hideState() {
        $stateMessage.classList.add('hidden');
    }

    /** 转义 HTML，防 XSS */
    function escapeHtml(str) {
        if (str == null) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    /** 格式化日期为友好显示（YYYY-MM-DD → YYYY 年 MM 月 DD 日） */
    function formatDateDisplay(dateStr) {
        const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr || '');
        if (!m) return dateStr || '';
        return `${m[1]} 年 ${m[2]} 月 ${m[3]} 日`;
    }

    /** 格式化发布时间（保留 HH:MM 或原样） */
    function formatTime(timeStr) {
        if (!timeStr) return '';
        // 支持 ISO 格式 / "YYYY-MM-DD HH:MM" / 纯时间
        const isoMatch = /T(\d{2}:\d{2})/.exec(timeStr);
        if (isoMatch) return isoMatch[1];
        const dtMatch = /(\d{2}:\d{2})/.exec(timeStr);
        if (dtMatch) return dtMatch[1];
        return timeStr;
    }

    // ============================================
    // 渲染：日期列表
    // ============================================
    function renderDateList(dates) {
        // 桌面端：左侧栏列表
        $sidebar.innerHTML = '';
        // 移动端：水平 pill
        $datePickerM.innerHTML = '';

        if (!dates || dates.length === 0) {
            const emptyLi = document.createElement('li');
            emptyLi.textContent = '暂无历史';
            emptyLi.style.cursor = 'default';
            emptyLi.style.color = 'var(--text-muted)';
            $sidebar.appendChild(emptyLi);
            return;
        }

        dates.forEach((date) => {
            // 桌面端
            const li = document.createElement('li');
            li.textContent = date;
            li.dataset.date = date;
            if (date === currentDate) li.classList.add('active');
            li.addEventListener('click', () => switchDate(date));
            $sidebar.appendChild(li);

            // 移动端
            const pill = document.createElement('span');
            pill.className = 'date-pill';
            pill.textContent = date;
            pill.dataset.date = date;
            if (date === currentDate) pill.classList.add('active');
            pill.addEventListener('click', () => switchDate(date));
            $datePickerM.appendChild(pill);
        });
    }

    /** 更新日期列表的高亮状态 */
    function updateDateActive() {
        document.querySelectorAll('.date-list li, .date-pill').forEach((el) => {
            if (el.dataset.date === currentDate) {
                el.classList.add('active');
            } else {
                el.classList.remove('active');
            }
        });
    }

    // ============================================
    // 渲染：卡片列表
    // ============================================
    function renderCards(items) {
        $cardList.innerHTML = '';

        if (!items || items.length === 0) {
            showState('暂无资讯数据，请等待每日 09:00 自动更新');
            return;
        }

        hideState();

        items.forEach((item) => {
            const card = document.createElement('article');
            card.className = 'card';

            // 字段提取（容错）
            const title    = item.title || '（无标题）';
            const url      = item.url || item.link || '#';
            const source   = item.source || '其他';
            const time     = formatTime(item.time || item.published_at || item.publish_time);
            const summary  = item.summary || item.description || '';
            const score    = typeof item.score === 'number' ? item.score : null;

            // 评分百分比（按 0-10 分制；如果是 0-100 则自动适配）
            let scorePct = 0;
            let scoreText = '';
            if (score !== null) {
                if (score <= 10) {
                    scorePct = (score / 10) * 100;
                    scoreText = score.toFixed(1);
                } else {
                    scorePct = Math.min(score, 100);
                    scoreText = String(Math.round(score));
                }
            }

            // 拼接 HTML
            let html = `
                <h3 class="card-title">
                    <a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(title)}</a>
                </h3>
                <div class="card-header">
                    <span class="source-tag" data-source="${escapeHtml(source)}">${escapeHtml(source)}</span>
                    ${time ? `<span class="card-time">${escapeHtml(time)}</span>` : ''}
                </div>
            `;

            if (summary) {
                html += `<p class="card-summary">${escapeHtml(summary)}</p>`;
            }

            if (score !== null) {
                html += `
                    <div class="card-rating">
                        <span class="rating-label">评分</span>
                        <div class="rating-bar">
                            <div class="rating-fill" style="width: ${scorePct}%"></div>
                        </div>
                        <span class="rating-score">${escapeHtml(scoreText)}</span>
                    </div>
                `;
            }

            card.innerHTML = html;
            $cardList.appendChild(card);
        });
    }

    // ============================================
    // 数据加载
    // ============================================

    /** 加载日期索引（data/index.json） */
    async function loadIndex() {
        const resp = await fetch('data/index.json', { cache: 'no-cache' });
        if (!resp.ok) throw new Error(`索引加载失败: HTTP ${resp.status}`);
        const data = await resp.json();
        if (!Array.isArray(data)) throw new Error('索引格式错误：应为数组');
        return data;
    }

    /** 加载某天数据（data/YYYY-MM-DD.json） */
    async function loadDateData(date) {
        const resp = await fetch(`data/${date}.json`, { cache: 'no-cache' });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        // 支持 {items: [...]} 或 [...] 两种格式
        if (Array.isArray(data)) return data;
        if (Array.isArray(data.items)) return data.items;
        return [];
    }

    // ============================================
    // 切换日期
    // ============================================
    async function switchDate(date) {
        if (!date || date === currentDate) return;
        currentDate = date;
        $currentDate.textContent = formatDateDisplay(date);
        updateDateActive();
        showState('正在加载…');

        try {
            const items = await loadDateData(date);
            renderCards(items);
        } catch (err) {
            console.error('加载日期数据失败:', err);
            showState(`加载失败：${err.message || '未知错误'}`, true);
        }
    }

    // ============================================
    // 初始化
    // ============================================
    async function init() {
        showState('正在加载…');

        try {
            dateIndex = await loadIndex();
        } catch (err) {
            console.error('加载索引失败:', err);
            showState(`加载失败：${err.message || '未知错误'}`, true);
            renderDateList([]);
            return;
        }

        // 索引为空 → 显示友好提示
        if (dateIndex.length === 0) {
            $currentDate.textContent = '暂无数据';
            renderDateList([]);
            showState('暂无资讯数据，请等待每日 09:00 自动更新');
            return;
        }

        // 渲染日期列表，默认加载最新（第一个）
        renderDateList(dateIndex);
        await switchDate(dateIndex[0]);
    }

    // 启动
    document.addEventListener('DOMContentLoaded', init);
})();
