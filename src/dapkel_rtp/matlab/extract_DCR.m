currentFolder = pwd;

% =============================================================================
% Parameters — adjust as needed
% =============================================================================
folder   = "./test_timing_matlab/";
nframes  = 10000;           % frames per .bin file
clk_period = 5e-9;          % 200 MHz clock

% Exposure time per frame.
% If chip_timing=1 (external trigger), read from frame_rate_cnt.txt;
% otherwise set exp_time_per_frame directly in seconds.
cnt_file = folder + "frame_rate_cnt.txt";
if isfile(cnt_file)
    frame_rate_cnt   = readmatrix(cnt_file);
    exp_time_per_frame = frame_rate_cnt(1) * clk_period;
    fprintf('Frame period from frame_rate_cnt.txt: %.6f ms\n', exp_time_per_frame*1e3);
else
    exp_time_per_frame = 20e-6;   % fallback: set manually
    fprintf('frame_rate_cnt.txt not found — using %.1f us\n', exp_time_per_frame*1e6);
end

% =============================================================================
% Discover .bin files
% =============================================================================
files = dir(fullfile(folder, 'data*.bin'));
nacq  = numel(files);
fprintf('Found %d acquisition files.\n', nacq);

% =============================================================================
% Accumulate photon counts over all files
% =============================================================================
photon_sum = zeros(32, 32);   % sum across all frames and acquisitions

for iiii = 1:nacq
    filepath = fullfile(folder, files(iiii).name);
    [~, photon_counts] = kelpie_data_ddr3(filepath, nframes);
    photon_sum = photon_sum + squeeze(sum(photon_counts, 3));
    fprintf('Decoded %d/%d: %s\n', iiii, nacq, files(iiii).name);
end

% =============================================================================
% DCR calculation  [counts / second / pixel]
% =============================================================================
total_time = nframes * nacq * exp_time_per_frame;   % total exposure per pixel
DCR = photon_sum / total_time;                       % [cps]

fprintf('\nDCR stats (cps):\n');
fprintf('  Min:    %.1f\n', min(DCR(:)));
fprintf('  Median: %.1f\n', median(DCR(:)));
fprintf('  Mean:   %.1f\n', mean(DCR(:)));
fprintf('  Max:    %.1f\n', max(DCR(:)));

% =============================================================================
% Plots
% =============================================================================
figure;
imagesc(fliplr(DCR));
colorbar;
colormap("hot");
pbaspect([1 1 1]);
title(sprintf('DCR map [cps]  —  %d acq × %d frames', nacq, nframes));
xlabel('Column'); ylabel('Row');

figure;
DCR_sorted = sort(DCR(:));
semilogy(DCR_sorted, 'b.-');
grid on;
xlabel('Pixel rank'); ylabel('DCR [cps]');
title('Sorted DCR per pixel');

% =============================================================================
% Save
% =============================================================================
save(fullfile(folder, 'DCR_result.mat'), 'DCR', 'exp_time_per_frame', 'nframes', 'nacq');
fprintf('Saved DCR_result.mat to %s\n', folder);
