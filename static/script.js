document.addEventListener('DOMContentLoaded', function() {
    // Global variables to store state
    let currentProcessId = null;
    let analysisResults = null;
    let availableQueries = [];
    let availableOptions = {};
    let allFrames = [];
    
    // Elements
    const uploadForm = document.getElementById('upload-form');
    const addQueryBtn = document.getElementById('add-query');
    const queriesContainer = document.getElementById('queries-container');
    const processStatus = document.getElementById('process-status');
    const statusMessage = document.getElementById('status-message');
    const progressBar = document.getElementById('progress-bar');
    const resultsSection = document.getElementById('results-section');
    
    // Query form elements
    const queryForm = document.getElementById('query-form');
    const rootQueryType = document.getElementById('root-query-type');
    const conditionsContainer = document.getElementById('conditions-container');
    const addConditionBtn = document.getElementById('add-condition');
    const queryStatus = document.getElementById('query-status');
    const queryStatusMessage = document.getElementById('query-status-message');
    const queryProgressBar = document.getElementById('query-progress-bar');
    const queryResults = document.getElementById('query-results');
    const queryVideoPlayer = document.getElementById('query-video-player');
    
    // Video viewer elements
    const videoPlayer = document.getElementById('video-player');
    const frameSlider = document.getElementById('frame-slider');
    const currentFrameIndex = document.getElementById('current-frame-index');
    const frameData = document.getElementById('frame-data');
    const frameGallery = document.getElementById('frame-gallery');
    const resultsTable = document.getElementById('results-table');
    const downloadJsonBtn = document.getElementById('download-json');
    
    // Initialize the form
    initializeForm();
    
    // Event listeners
    uploadForm.addEventListener('submit', handleUpload);
    addQueryBtn.addEventListener('click', addQuery);
    queriesContainer.addEventListener('click', handleQueryRemove);
    addConditionBtn.addEventListener('click', addCondition);
    queryForm.addEventListener('submit', handleQuerySubmit);
    frameSlider.addEventListener('input', handleFrameSliderChange);
    downloadJsonBtn.addEventListener('click', downloadResultsJson);
    
    function initializeForm() {
        // Add initial query
        if (queriesContainer.children.length === 0) {
            addQuery();
        }
    }
    
    function addQuery() {
        const queryItem = document.createElement('div');
        queryItem.className = 'query-item mb-3 p-3 border rounded';
        queryItem.innerHTML = `
            <div class="mb-2 d-flex justify-content-between align-items-center">
                <label class="form-label">Query</label>
                <button type="button" class="btn btn-sm btn-danger remove-query"><i class="bi bi-trash"></i></button>
            </div>
            <input type="text" class="form-control mb-2 query-text" placeholder="E.g., Is the driver present in the forklift?" required>
            
            <label class="form-label">Options (comma-separated)</label>
            <input type="text" class="form-control options-text" placeholder="E.g., yes, no" required>
        `;
        
        queriesContainer.appendChild(queryItem);
        
        // Show remove buttons if there are multiple queries
        toggleRemoveButtons();
    }
    
    function toggleRemoveButtons() {
        const removeButtons = document.querySelectorAll('.remove-query');
        const showButtons = queriesContainer.children.length > 1;
        
        removeButtons.forEach(button => {
            button.style.display = showButtons ? 'block' : 'none';
        });
    }
    
    function handleQueryRemove(event) {
        if (event.target.closest('.remove-query')) {
            const button = event.target.closest('.remove-query');
            const queryItem = button.closest('.query-item');
            
            queryItem.remove();
            toggleRemoveButtons();
        }
    }
    
    async function handleUpload(event) {
        event.preventDefault();
        
        // Get form data
        const videoFile = document.getElementById('video-file').files[0];
        if (!videoFile) {
            alert('Please select a video file');
            return;
        }
        
        // Get query data
        const queries = [];
        const queryItems = queriesContainer.querySelectorAll('.query-item');
        queryItems.forEach(item => {
            const queryText = item.querySelector('.query-text').value;
            const optionsText = item.querySelector('.options-text').value;
            const options = optionsText.split(',').map(option => option.trim()).filter(option => option);
            
            if (queryText && options.length > 0) {
                queries.push({
                    query: queryText,
                    options: options
                });
                
                // Store for query builder
                availableQueries.push(queryText);
                availableOptions[queryText] = options;
            }
        });
        
        if (queries.length === 0) {
            alert('Please add at least one query with options');
            return;
        }
        
        // Get other config params
        const context = document.getElementById('context').value;
        const fps = parseFloat(document.getElementById('fps').value);
        const frameStride = parseInt(document.getElementById('frame-stride').value);
        const maxWidth = parseInt(document.getElementById('max-width').value);
        const maxHeight = parseInt(document.getElementById('max-height').value);
        const tileRows = parseInt(document.getElementById('tile-rows').value);
        const tileCols = parseInt(document.getElementById('tile-cols').value);
        
        // Create config object
        const config = {
            queries: queries,
            context: context,
            fps: fps,
            frame_stride: frameStride,
            max_resolution: [maxWidth, maxHeight],
            tile_frames: [tileRows, tileCols]
        };
        
        // Create form data for upload
        const formData = new FormData();
        formData.append('video', videoFile);
        formData.append('config_data', JSON.stringify(config));
        
        // Show processing status
        processStatus.style.display = 'block';
        statusMessage.textContent = 'Uploading video...';
        progressBar.style.width = '0%';
        
        try {
            // Upload video and config
            const response = await fetch('/api/upload', {
                method: 'POST',
                body: formData
            });
            
            if (!response.ok) {
                throw new Error(`Upload failed: ${response.statusText}`);
            }
            
            const data = await response.json();
            currentProcessId = data.id;
            
            // Start polling for status
            pollProcessStatus(currentProcessId);
            
        } catch (error) {
            console.error('Error:', error);
            statusMessage.textContent = `Error: ${error.message}`;
            progressBar.className = 'progress-bar bg-danger';
            progressBar.style.width = '100%';
        }
    }
    
    async function pollProcessStatus(processId) {
        try {
            const response = await fetch(`/api/status/${processId}`);
            
            if (!response.ok) {
                throw new Error(`Status check failed: ${response.statusText}`);
            }
            
            const data = await response.json();
            
            // Update progress bar
            progressBar.style.width = `${data.progress}%`;
            statusMessage.textContent = data.message;
            
            if (data.status === 'completed') {
                // Process completed successfully
                progressBar.className = 'progress-bar bg-success';
                
                // Load results
                await loadResults(processId, data);
                
            } else if (data.status === 'failed') {
                // Process failed
                progressBar.className = 'progress-bar bg-danger';
                
            } else {
                // Still processing, poll again after 2 seconds
                setTimeout(() => pollProcessStatus(processId), 2000);
            }
            
        } catch (error) {
            console.error('Polling error:', error);
            statusMessage.textContent = `Error: ${error.message}`;
            progressBar.className = 'progress-bar bg-danger';
            progressBar.style.width = '100%';
        }
    }
    
    async function loadResults(processId, statusData) {
        try {
            // Fetch the results data
            const response = await fetch(`/api/results/${processId}`);
            
            if (!response.ok) {
                throw new Error(`Failed to load results: ${response.statusText}`);
            }
            
            analysisResults = await response.json();
            
            // Load video
            if (statusData.video_url) {
                videoPlayer.src = statusData.video_url;
                videoPlayer.load();
            }
            
            // Load frames
            if (statusData.frames_dir) {
                await loadFrames(statusData.frames_dir);
            }
            
            // Initialize query builder
            initializeQueryBuilder();
            
            // Update results table
            updateResultsTable();
            
            // Show results section
            resultsSection.style.display = 'block';
            
        } catch (error) {
            console.error('Error loading results:', error);
            statusMessage.textContent = `Error loading results: ${error.message}`;
        }
    }
    
    async function loadFrames(framesDir) {
        try {
            const response = await fetch(framesDir);
            
            if (!response.ok) {
                throw new Error(`Failed to load frames: ${response.statusText}`);
            }
            
            allFrames = await response.json();
            
            // Update frame slider
            frameSlider.min = 0;
            frameSlider.max = allFrames.length - 1;
            frameSlider.value = 0;
            
            // Update gallery
            updateFrameGallery();
            
            // Update current frame display
            updateCurrentFrameDisplay(0);
            
        } catch (error) {
            console.error('Error loading frames:', error);
            frameGallery.innerHTML = `<p class="text-danger">Error loading frames: ${error.message}</p>`;
        }
    }
    
    function updateFrameGallery() {
        frameGallery.innerHTML = '';
        
        allFrames.forEach((frame, index) => {
            const thumbnail = document.createElement('div');
            thumbnail.className = 'frame-thumbnail';
            thumbnail.innerHTML = `
                <img src="${frame.url}" alt="Frame ${index}" class="img-thumbnail" style="width: 120px; height: 68px; object-fit: cover;">
            `;
            
            thumbnail.addEventListener('click', () => {
                updateCurrentFrameDisplay(index);
                frameSlider.value = index;
            });
            
            frameGallery.appendChild(thumbnail);
        });
    }
    
    function updateCurrentFrameDisplay(index) {
        // Highlight the selected thumbnail
        const thumbnails = frameGallery.querySelectorAll('.frame-thumbnail');
        thumbnails.forEach((thumb, i) => {
            if (i === parseInt(index)) {
                thumb.classList.add('active');
            } else {
                thumb.classList.remove('active');
            }
        });
        
        // Update current frame index display
        currentFrameIndex.textContent = index;
        
        // Find the matching analysis result closest to this frame
        if (analysisResults && analysisResults.length > 0) {
            // Get the timestamp from the frame filename
            const frameFileName = allFrames[index].name;
            const timestampMatch = frameFileName.match(/(\d+\.\d+)s/);
            
            if (timestampMatch) {
                const frameTimestamp = parseFloat(timestampMatch[1]);
                
                // Find the closest result
                let closestResult = analysisResults[0];
                let minDiff = Math.abs(frameTimestamp - closestResult.timestamp);
                
                for (let i = 1; i < analysisResults.length; i++) {
                    const diff = Math.abs(frameTimestamp - analysisResults[i].timestamp);
                    if (diff < minDiff) {
                        minDiff = diff;
                        closestResult = analysisResults[i];
                    }
                }
                
                // Update the display
                updateFrameDataDisplay(closestResult);
            }
        }
    }
    
    function updateFrameDataDisplay(data) {
        frameData.innerHTML = '';
        
        if (data) {
            // Create a table to display the data
            const table = document.createElement('table');
            table.className = 'table table-sm';
            
            // Add rows for each property
            for (const [key, value] of Object.entries(data)) {
                if (key !== 'error') {
                    const row = document.createElement('tr');
                    
                    const keyCell = document.createElement('td');
                    keyCell.className = 'fw-bold';
                    keyCell.textContent = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
                    
                    const valueCell = document.createElement('td');
                    valueCell.textContent = value;
                    
                    row.appendChild(keyCell);
                    row.appendChild(valueCell);
                    table.appendChild(row);
                }
            }
            
            // Display error if present
            if (data.error) {
                const errorDiv = document.createElement('div');
                errorDiv.className = 'alert alert-danger mt-2';
                errorDiv.textContent = `Error: ${data.error}`;
                frameData.appendChild(errorDiv);
            }
            
            frameData.appendChild(table);
        } else {
            frameData.innerHTML = '<p class="text-muted">No data available for this frame</p>';
        }
    }
    
    function handleFrameSliderChange() {
        const index = parseInt(frameSlider.value);
        updateCurrentFrameDisplay(index);
    }
    
    function updateResultsTable() {
        // Clear existing table content
        const tableHead = resultsTable.querySelector('thead tr');
        const tableBody = resultsTable.querySelector('tbody');
        
        // Keep only the timestamp header
        tableHead.innerHTML = '<th>Timestamp</th>';
        tableBody.innerHTML = '';
        
        if (!analysisResults || analysisResults.length === 0) {
            return;
        }
        
        // Get all unique keys from the results
        const allKeys = new Set();
        analysisResults.forEach(result => {
            Object.keys(result).forEach(key => {
                if (key !== 'timestamp' && key !== 'error') {
                    allKeys.add(key);
                }
            });
        });
        
        // Add headers for each key
        allKeys.forEach(key => {
            const th = document.createElement('th');
            th.textContent = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
            tableHead.appendChild(th);
        });
        
        // Add a row for each result
        analysisResults.forEach(result => {
            const row = document.createElement('tr');
            
            // Add timestamp cell
            const timestampCell = document.createElement('td');
            timestampCell.textContent = result.timestamp.toFixed(2) + 's';
            row.appendChild(timestampCell);
            
            // Add cells for each key
            allKeys.forEach(key => {
                const cell = document.createElement('td');
                cell.textContent = result[key] || '-';
                row.appendChild(cell);
            });
            
            tableBody.appendChild(row);
        });
    }
    
    function downloadResultsJson() {
        if (analysisResults) {
            const dataStr = JSON.stringify(analysisResults, null, 2);
            const dataBlob = new Blob([dataStr], { type: 'application/json' });
            const url = URL.createObjectURL(dataBlob);
            
            const a = document.createElement('a');
            a.href = url;
            a.download = 'video_analysis_results.json';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }
    }
    
    function initializeQueryBuilder() {
        // Clear existing conditions
        conditionsContainer.innerHTML = '';
        
        // Add first condition
        addCondition();
    }
    
    function addCondition() {
        const conditionItem = document.createElement('div');
        conditionItem.className = 'condition-item mb-3 p-3 border rounded';
        
        let queryOptions = '';
        availableQueries.forEach(query => {
            queryOptions += `<option value="${query}">${query}</option>`;
        });
        
        conditionItem.innerHTML = `
            <div class="mb-2 d-flex justify-content-between align-items-center">
                <label class="form-label">Condition</label>
                <button type="button" class="btn btn-sm btn-danger remove-condition"><i class="bi bi-trash"></i></button>
            </div>
            <div class="mb-3">
                <select class="form-select query-select">
                    ${queryOptions}
                </select>
            </div>
            <div class="mb-3">
                <label class="form-label">Options</label>
                <div class="options-checkboxes">
                    ${generateOptionsCheckboxes(availableQueries[0])}
                </div>
            </div>
        `;
        
        conditionsContainer.appendChild(conditionItem);
        
        // Add event listeners
        const querySelect = conditionItem.querySelector('.query-select');
        querySelect.addEventListener('change', function() {
            const optionsContainer = this.closest('.condition-item').querySelector('.options-checkboxes');
            optionsContainer.innerHTML = generateOptionsCheckboxes(this.value);
        });
        
        const removeBtn = conditionItem.querySelector('.remove-condition');
        removeBtn.addEventListener('click', function() {
            this.closest('.condition-item').remove();
        });
    }
    
    function generateOptionsCheckboxes(queryText) {
        if (!availableOptions[queryText]) {
            return '<p class="text-muted">No options available</p>';
        }
        
        let checkboxesHtml = '';
        availableOptions[queryText].forEach(option => {
            checkboxesHtml += `
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" value="${option}" id="option-${option.replace(/\s+/g, '-')}">
                    <label class="form-check-label" for="option-${option.replace(/\s+/g, '-')}">
                        ${option}
                    </label>
                </div>
            `;
        });
        
        return checkboxesHtml;
    }
    
    async function handleQuerySubmit(event) {
        event.preventDefault();
        
        if (!currentProcessId) {
            alert('Please upload and process a video first');
            return;
        }
        
        // Build the query
        const queryType = rootQueryType.value;
        const conditions = [];
        
        const conditionItems = conditionsContainer.querySelectorAll('.condition-item');
        conditionItems.forEach(item => {
            const queryText = item.querySelector('.query-select').value;
            const selectedOptions = [];
            
            const optionCheckboxes = item.querySelectorAll('.options-checkboxes input[type="checkbox"]:checked');
            optionCheckboxes.forEach(checkbox => {
                selectedOptions.push(checkbox.value);
            });
            
            if (selectedOptions.length > 0) {
                conditions.push({
                    query: queryText,
                    options: selectedOptions
                });
            }
        });
        
        if (conditions.length === 0) {
            alert('Please add at least one condition with selected options');
            return;
        }
        
        const queryData = {
            queries: [
                {
                    [queryType]: conditions
                }
            ]
        };
        
        // Show query status
        queryStatus.style.display = 'block';
        queryStatusMessage.textContent = 'Processing query...';
        queryProgressBar.style.width = '0%';
        queryResults.style.display = 'none';
        
        try {
            // Submit the query
            const formData = new FormData();
            formData.append('process_id', currentProcessId);
            formData.append('query_data', JSON.stringify(queryData));
            
            const response = await fetch('/api/query', {
                method: 'POST',
                body: formData
            });
            
            if (!response.ok) {
                throw new Error(`Query submission failed: ${response.statusText}`);
            }
            
            const data = await response.json();
            
            // Poll for query status
            pollQueryStatus(data.id);
            
        } catch (error) {
            console.error('Error:', error);
            queryStatusMessage.textContent = `Error: ${error.message}`;
            queryProgressBar.className = 'progress-bar bg-danger';
            queryProgressBar.style.width = '100%';
        }
    }
    
    async function pollQueryStatus(queryId) {
        try {
            const response = await fetch(`/api/status/${queryId}`);
            
            if (!response.ok) {
                throw new Error(`Status check failed: ${response.statusText}`);
            }
            
            const data = await response.json();
            
            // Update progress bar
            queryProgressBar.style.width = `${data.progress}%`;
            queryStatusMessage.textContent = data.message;
            
            if (data.status === 'completed') {
                // Query completed successfully
                queryProgressBar.className = 'progress-bar bg-success';
                
                // Load query results
                if (data.video_url) {
                    queryResults.style.display = 'block';
                    queryVideoPlayer.src = data.video_url;
                    queryVideoPlayer.load();
                }
                
            } else if (data.status === 'failed') {
                // Query failed
                queryProgressBar.className = 'progress-bar bg-danger';
                
            } else {
                // Still processing, poll again after 2 seconds
                setTimeout(() => pollQueryStatus(queryId), 2000);
            }
            
        } catch (error) {
            console.error('Polling error:', error);
            queryStatusMessage.textContent = `Error: ${error.message}`;
            queryProgressBar.className = 'progress-bar bg-danger';
            queryProgressBar.style.width = '100%';
        }
    }
});