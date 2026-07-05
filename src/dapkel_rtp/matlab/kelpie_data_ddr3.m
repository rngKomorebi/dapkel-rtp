function [time_series, photon_counts] = kelpie_data_ddr3(filepath, nframes)

    ranges = {
        1:64, ...
        65:64+64, ...
        1+(64*2):64*3, ...
        1+(64*3):64*4, ...
        1+(64*4):64*5, ...
        1+(64*5):64*6, ...
        1+(64*6):64*7, ...
        1+(64*7):64*8
    };

    file = fopen(filepath, 'rb');
    if file == -1
        error('kelpie_data_ddr3: cannot open file: %s', filepath);
    end
    raw_data = uint8(fread(file, [4*nframes*64*8,1], 'uint8','b'));
    fclose(file);

    ddr3_mem = zeros(64*nframes, 32, "uint8"); %for each frame, removed *32
    cnt =1; %basically
    for ii=1:length(raw_data)/32 %length(raw_data)/32
        ddr3_mem(cnt,:) = raw_data((ii-1)*32+1:32*ii);
        cnt = cnt+1;
    end
    
    %%DDR3 MEM is correctly set up, need to check the ordering of the pixels
    
    % ddr3_mem_cleanup = zeros(64*nframes, 32, "uint8");
    % 
    % chunk_size = 8;
    % for k = 0:3
    %         indx_start = k * chunk_size + 1;
    %         indx_end = (k+1) * chunk_size;
    % 
    %         ddr3_mem_cleanup(:, indx_start:indx_end) = ddr3_mem(:, indx_end:-1:indx_start);
    % end
    % 
    % % For each 8-byte block (total 4 per row)
    % for i = 0:3
    %     blk_start = i * 8 + 1;
    %     blk_end   = blk_start + 7;
    % 
    %    ddr3_mem(:, blk_start:blk_end) = ddr3_mem_cleanup(:, blk_start + [4 5 6 7 0 1 2 3]);
    % end

    % data_raw = zeros(size(raw_data,1)/4,1);
    % kk=1;
    % for ii = 1:size(data_raw,1)
    %     data_raw(ii,1) = uint32(raw_data(kk))+uint32(raw_data(kk+1))*256+uint32(raw_data(kk+2))*65536+uint32(raw_data(kk+3))*16777216;
    %     kk = kk+4;
    % end
    ddr_3_mem_resh = zeros(64*nframes*8,4,"uint32");
    for kk=1:nframes
        for ii=1:8
            ddr_3_mem_resh((kk-1)*64*8+(ii-1)*64+1:(kk-1)*64*8+ii*64,:) = ddr3_mem((kk-1)*64+1:kk*64,(ii-1)*4+1:ii*4);
        end
    end
    % chatgpt
    % raw_data = uint32(raw_data(:));  % ensure column and uint32
    raw_data = uint32(reshape(ddr_3_mem_resh', 4, []));  % group every 4 bytes per word
    data_raw = raw_data(4,:) + bitshift(raw_data(3,:),8) ...
              + bitshift(raw_data(2,:),16) + bitshift(raw_data(1,:),24);

    data_raw = data_raw.';  % column vector
    % data_raw_resh = reshape(data_raw', [nframes*64 8]);

    %%
    % bin_all = zeros(1792*nframes,8); % preallocate for speed
    % % bin_all = zeros(2048*nframes,8); % preallocate for speed
    % 
    % for jj=1:nframes
    %     for i = 1:8
    %         bin_data = data_raw(ranges{i}+(jj-1)*64*8);
    %         bin_data = dec2bin(bin_data,32);
    %         bin_data = bin_data(:,5:32);
    %         bin_data_resh = reshape(bin_data',[28*64 1]);
    %         bin_data_resh = bin2dec(bin_data_resh);
    %         bin_all(1+(jj-1)*1792:jj*1792,i) = bin_data_resh; % assign as column i
    % 
    %     end
    % end

    % chatgpt
    bin_all = false(1792*nframes, 8);  % logical (faster and smaller than double)

    bit_positions = fliplr(uint8(1:28));       % we need bits 5–32 (LSB=1, MSB=32)
    
    for jj = 1:nframes
        frame_offset = (jj-1)*64*8;
    
        for i = 1:8
            % Get 64 uint32 words for this frame/channel
            bin_data = data_raw(ranges{i} + frame_offset);
            bits_5_32 = zeros(64,28);
            for kk = 1:64
                % Extract bits 5–32 as logical matrix (64x28)
                bits_5_32(kk,:) = bitget(bin_data(kk), bit_positions, "uint32");
            end
            % Flatten to one long column (1792x1)
            bin_all(1+(jj-1)*1792:jj*1792, i) = reshape(bits_5_32', [28*64 1]);
        end
    end

    
    %%
    
    % for kk=1:nframes
    %     for jj = 1:8
    %         off = 4*(jj-1); % column offset
    %         row = 1;
    %         cnt = 1;
    %         for ii = 1:128
    %             pix_tmp = bin_all(1+(ii-1)*14+(kk-1)*1792:ii*14+(kk-1)*1792, jj);
    %             % pix_tmp(10) = ~pix_tmp(10);
    %             cnt_tmp = pix_tmp(1:9);
    %             coarse_time = pix_tmp(1:10);
    %             fine_tmp = pix_tmp(11:14);
    %             photons = cnt_tmp' * conv';
    %             time_fine = fine_tmp' * conv1';
    %             time_coarse = coarse_time'*conv2';
    %             photon_counts(row, cnt + off,kk) = photons;
    %             time_series(row, cnt+off,kk) = time_coarse*8+time_fine-1;
    %             cnt = cnt + 1;
    %             if cnt == 5
    %                 cnt = 1;
    %                 row = row + 1;
    %             end
    %         end
    %     end
    % end

    conv  = [256 128 64 32 16 8 4 2 1];
    conv1 = [8 4 2 1];
    conv2 = [512 256 128 64 32 16 8 4 2 1];

photon_counts = zeros(32, 32, nframes);
time_series   = zeros(32, 32, nframes);
time_fine_series = zeros(32, 32, nframes);
for kk = 1:nframes
    for jj = 1:8
        off = 4*(jj-1); % column offset
        row = 1;
        cnt = 1;

        % Extract bits for this frame/channel
        bits_frame = bin_all((kk-1)*1792+1 : kk*1792, jj);

        for ii = 1:128
            % Each pixel = 14 bits
            pix_tmp = bits_frame((ii-1)*14+1 : ii*14);

            % Split into fields
            cnt_tmp     = pix_tmp(1:9);
            coarse_time = pix_tmp(1:10);
            fine_tmp    = pix_tmp(11:14);

            % Binary → decimal (dot product with precomputed weights)
            photons      = conv * double(cnt_tmp);
            time_fine    = conv1 * double(fine_tmp);
            time_fine_series(row, cnt + off, kk)   = time_fine;

            time_coarse  = conv2 * double(coarse_time);
            photon_counts(row, cnt + off, kk) = photons;
            % if time_fine > 4
            %     time_fine = time_fine-5;
            % else
            %     time_fine = time_fine+3;
            % end
            if time_fine < 4
                time_coarse = time_coarse-1;
            else
                time_coarse = time_coarse;
            end
            % if time_fine == 0
            %     time_fine =7;
            % elseif time_fine == 7
            %     time_fine =0;
            % end
            % if row==5
            %     if cnt + off == 8
            %         hello = 1;
            %     end
            % end
            
            time_series(row, cnt + off, kk)   = (time_coarse-1)*8 + (8-time_fine);

            cnt = cnt + 1;
            if cnt == 5
                cnt = 1;
                row = row + 1;
            end
        end
    end
end