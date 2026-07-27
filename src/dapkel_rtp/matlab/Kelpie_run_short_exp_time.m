currentFolder = pwd;% fclose('all');close all;clear all;

% General Parameters.
nbits                               = 17*(32*32)-1;
clk_period                          = 5e-9;
% exp_time                            = 0e-6; % 9 us; 1e-6 -- 10 us, 2e-6 -- 11 us; 9e-6 + exp_time
exp_time                            = 10e-3-9e-6; % 10 ms
exposure_time                       = round(exp_time/clk_period);
nframes                             = 10000; % Up to 2e9/1.7e3 = 1.1 million frames; nothing comes -- zeroes; per file per macropixel
nacq                                = 100;

chip_debug                          = 0;
chip_timing                         = 1;
clk_shift                           = 0;
chip_artif_rdout                    = 0;
single_shot_noise                   = 0; % 1-->noise 0-->singleshot
memory_select0                      = 0;
memory_select1                      = 0;
debug_last_row                      = 0;
external_frame_trigger              = 0; % 1 = wait for external SMA sync trigger to start each frame (separate feature)
chip_config  = bin2dec(dec2bin(2^8*external_frame_trigger+2^7*debug_last_row+ 2^6*memory_select1+ ...
    2^5*memory_select0+2^4*single_shot_noise+ ...
    2^2*chip_artif_rdout+2^1*chip_timing+chip_debug,3));

% folder = "./jitter_OR_VRO1V10_VDD1V16/";
% folder = "./jitter_SS0_VOP22V0_VRO1V10_VDD1V16_las7803p26/";
% folder                              = "./density_VOP22V0_D1_M2_VDD1V2_2/";
% folder                              = "./density_VOP22V0_D1_M1_extclk/";
% folder                              = "./jitter_VOP22V0_C4_D1_M2_extclk_VDD1v2/";
% folder                              = "./NIROT_VOP22V0_S3_D1_M2_extclk_VDD1v19_laspow6_100k_1/";
folder                              = "./test_timing/";

% folder                              = "./noSPADs_timing/";

% folder                              = "./VBRK_S0_V22V0/";
% folder                              = "./DCR_S1_V20V0/";
% folder                              = "./xtalk_coincS0S3_V22V0/";

% folder = "./test/"
% folder = "./jitter_1_S3/"

filename                            = "data";
% filename = "testtest";

filepath                            = folder + filename + ".bin";
program_file                        = "./program_ORT.txt";

%% Configure the board power management
str = sprintf('"%s\\Kelpie_v2_pwr_mgt.exe" %d %s %s %s %s %d', ...
                   currentFolder, nbits, program_file, program_file, program_file, program_file, clk_shift);
system(str);
%% Make the actual acquisition with the parameters set before
tic
for iiii=1:nacq
    filename1 = filename+num2str(iiii);
    filepath = folder + filename1 + ".bin";
    str = sprintf('"%s\\Kelpie_v2.exe" %d %d %d %s %s', ...
                   currentFolder, chip_config, exposure_time, ...
                   nframes, folder, filename1);
    system(str);
    disp(iiii)
end
toc
%% Decode timestamps and photon counts

photon_counts = zeros(32,32,nframes,nacq);
time_mat = zeros(32,32,nframes,nacq);
tic
for iiii=1:nacq
    filename1 = filename;%+num2str(iiii);
    filepath = folder + filename1 + ".bin";
    [time_mat(:,:,:,iiii), photon_counts(:,:,:,iiii)] = kelpie_data_ddr3(filepath,nframes); 
    disp(iiii)
end
toc

%% Save data
save("test.mat","time_mat");

% save("NIROT_VOP22V0_S3_D1_M2_extclk_VDD1v19_laspow6_100k_1.mat","time_mat");

% save("noSPADs_timing.mat","time_mat");

%% Load data
time_mat_jitter = load("test.mat","time_mat");
% time_mat_jitter = load("NIROT_VOP22V0_S1_D1_M2_extclk_VDD1v19_laspow6_100k_1.mat","time_mat");

time_mat_jitter = time_mat_jitter.time_mat;

time_coarse_jitter = floor((time_mat_jitter)/8) + 1;
time_fine_jitter = mod((time_mat_jitter),8);
%%
bin_ax = 0:1700;
bin_ax_coarse = 1:1700;
bin_ax_fine = 1:1700;

pixx = 12;
pixy = 12;
% pixx = 10;
% pixy = 26;
f = figure;
histogram(squeeze(time_mat_jitter(pixx,pixy,:,1)),bin_ax);
% histogram(squeeze(time_coarse_jitter(pixx,pixy,:,1)),bin_ax_coarse);
% histogram(squeeze(time_fine_jitter(pixx,pixy,:,1)),bin_ax_fine);

xlabel("Time code [#]");
ylabel("Counts [#]");
% xlim([0 180]);
% ylim([1 2000])
% yscale("log");
%%
bin_ax = 1:1:330;
histos = zeros(32,32,numel(bin_ax)-1);
for ii=1:32
    for jj=1:32
        histos(ii,jj,:) = histcounts(squeeze(time_mat_jitter(ii,jj,:,1)), bin_ax);
        
    end
end
%%
pixx = 11;
pixy = 15;
figure;
semilogy(circshift(squeeze(histos(pixx,pixy,:)),100));
grid on
%% make an image
img_int = squeeze(sum(histos,3));

figure;
imagesc(img_int);
colorbar
%%
line_plot = squeeze(img_int(:,19));
figure;
semilogy(line_plot)
%%
Laser_pow = [8.8e-3 6.06e-3 5.0e-3 4.6e-3 2.5e-3 1.3e-3 687e-6 162e-6];
Laser_rot = [5.57 5 4.68 4.57 4 3.57 3.3 3];
figure;
plot(Laser_rot, Laser_pow)
%% 
pixx = 2;
pixy = 19;
time_to_plot = squeeze(time_coarse_jitter(pixx,pixy,:,1));
idx = time_to_plot <1;
time_to_plot(idx) = [];
figure;
plot(time_to_plot);
figure;
plot(squeeze(time_fine_jitter(pixx,pixy,:,1)));
%% Plot the dark count distribution
img_plot = squeeze(photon_counts(:,:,5));%./(exp_time);
imagesc(img_plot);
colorbar
%% Plot the dark count distribution
imagesc(squeeze(sum(photon_counts,3)));
colorbar
%%
exp_total_time = exp_time*nframes;
DCR = squeeze(sum(photon_counts,3))/exp_total_time;
DCR = sort(DCR(:));
figure;
semilogy(DCR)
%%
DCR                             = photon_counts;
DCR                             = squeeze(sum(DCR,3))/exp_total_time;
%%
exp_total_time                  = exp_time*nframes;
Area                            = (10.17e-6)^2;
wavelength                      = 530;
Hama_resp                       = (0.267+0.279)/2;
PD_cur                          = 0.480e-6;
Pow                             = PD_cur/Hama_resp;
Irradiance                      = Pow/0.0001;
PowerSpad                       = Irradiance*Area;
Nphoton                         = PowerSpad.*wavelength/(1e9*(6.626e-34)*299792458);
% NPhoton_Kelpie                  = squeeze(sum(photon_counts,3))/exp_total_time;
PDE_pixel                       = (NPhoton_Kelpie-DCR)./Nphoton*100;
figure;
imagesc(PDE_pixel)
colorbar

