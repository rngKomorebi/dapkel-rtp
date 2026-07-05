currentFolder = pwd;% fclose('all');close all;clear all;

% General Parameters.
nbits = 17*(32*32)-1;

% For OR tree
lut = 32767; 
lut_r = 65534; 
% For Single SPAD 0
lut = 21845;
lut_r = 87380;
% lut = 131068;
% lut = 0;   

clk_period = 5e-9;
% exp_time = 8000e-6;
exp_time = 20e-6;

exposure_time                       = round(exp_time/clk_period);
nframes                             = 800;
nacq                                = 1000;
chip_debug                          = 0;
chip_timing                         = 1;
clk_shift                           = 2400;
chip_artif_rdout                    = 0;
single_shot_noise                   = 0; % 1-->noise 0-->singleshot
memory_select0                      = 0;
memory_select1                      = 0;
debug_last_row                      = 0;
chip_config  = bin2dec(dec2bin(2^6*debug_last_row+ 2^5*memory_select1+ ...
    2^4*memory_select0+2^3*single_shot_noise+ ...
    2^2*chip_artif_rdout+2^1*chip_timing+chip_debug,3));
% folder = "./jitter_OR_VRO1V10_VDD1V16/";

% folder = "./jitter_SS0_VOP22V0_VRO1V10_VDD1V16_las7803p26/";
% folder = "./singleshot_VRO1V10_VDD1V14/";
folder = "./test/"

% folder = "./jitter_1_S3/"

filename = "data";
% filename = "testtest";

filepath = folder + filename + ".bin";
program_file = "./program_ORC.txt";

str = sprintf('"%s\\Kelpie_v2_pwr_mgt.exe" %d %s %s %s %s %d', ...
                   currentFolder, nbits, program_file, program_file, program_file, program_file, clk_shift);
system(str);

%%
figure;
for iiii=1:nacq
    photon_counts = zeros(32,32,1,1);
    time_mat = zeros(32,32,1,1);
    filename1 = filename;%+num2str(iiii);
    filepath = folder + filename1 + ".bin";
    str = sprintf('"%s\\Kelpie_v2.exe" %d %d %d %s %s', ...
                   currentFolder, chip_config, exposure_time, ...
                   nframes, folder, filename1);
    system(str);
    [time_mat(:,:,1,1), photon_counts(:,:,1,1)] = kelpie_data_ddr3(filepath,1); 
    img_save = (squeeze(photon_counts(:,:,1,1)));
    imagesc(fliplr(img_save));
    pbaspect([1 1 1]);
    colorbar;
    colormap("gray");
    
    pause(0.5);
    disp(iiii)
end
