/* StickLLM: Board+Tile bundle — avoids StickLink parallel fetch flake on Board.js */
/**
 * 
 */
"use strict";

class Board {

	constructor(id, width, height, num_bombs, seed, gameType) {

		//console.log("Creating a new board with id=" + id + " ...");

		this.MAX = 4294967295;

		this.id = id;
		this.gameType = gameType;
		this.width = width;
		this.height = height;
		this.num_bombs = num_bombs;
		this.seed = seed;

		this.tiles = [];
		this.started = false;
		this.bombs_left = this.num_bombs;

		this.init_tiles();

		this.gameover = false;
		this.won = false;

		this.highDensity = false;

		this.compressor = new Compressor();

		this.uid = Math.random(this.MAX);

		// information calculated within the solver
		this.nextMoves = [];       // Action
		this.safeTiles = [];       // Tile  
		this.unflaggedMines = [];  // Tile
		this.deadTiles = [];       // Tile
		this.considered = [];      // Tile

		this.bestTree = null;      // BestTree

		Object.seal(this) // prevent new properties being created
	}

	reset() {

		this.nextMoves = [];
		this.safeTiles = [];
		this.unflaggedMines = [];
		this.deadTiles = [];
		this.considered = [];

	}

	isStarted() {
		return this.started;
	}
	
	setGameLost() {
		this.gameover = true;
	}

    setGameWon() {
        this.gameover = true;
        this.won = true;
    }

	isGameover() {
		return this.gameover;
	}
	
	
	getID() {
		return this.id;
	}
	
	setStarted() {
		
		if (this.start) {
			console.log("Logic error: starting the same game twice");
			return;
		}
		
		this.started = true;
	}

	setHighDensity(tilesLeft, minesLeft) {

		if (minesLeft * 5 > tilesLeft * 2) {
			this.highDensity = true;
		} else {
			this.highDensity = false;
        }

    }

	isHighDensity() {
		return this.highDensity;
    }

	xy_to_index(x, y) {
		return y*this.width + x;
	}
	
	getTileXY(x, y) {

		if (x < 0 || x >= this.width || y < 0 || y >= this.height) {
			return null;
        }

		const index = this.xy_to_index(x,y);
		
		return this.tiles[index];
		
	}
	
	getTile(index) {
		
		return this.tiles[index];
		
	}
	
	// true if number of flags == tiles value
	// and number of unrevealed > 0
	canChord(tile) {
		
		let flagCount = 0;
		let coveredCount = 0;		
		for (let adjTile of this.getAdjacent(tile)) {
			if (adjTile.isFlagged()) {  
				flagCount++;
			}
			if (adjTile.isCovered() && !adjTile.isFlagged()) {  
				coveredCount++;
			}
		}
		
		return (flagCount == tile.getValue()) && (coveredCount > 0);
		
	}

    // return number of confirmed mines adjacent to this tile
    adjacentFoundMineCount(tile) {

        let mineCount = 0;
        for (let adjTile of this.getAdjacent(tile)) {
			if (adjTile.isSolverFoundBomb()) {
                mineCount++;
            }
        }

        return mineCount;

    }

	// return number of flags adjacent to this tile
	adjacentFlagsPlaced(tile) {

		let flagCount = 0;
		for (let adjTile of this.getAdjacent(tile)) {
			if (adjTile.isFlagged()) {
				flagCount++;
			}
		}

		return flagCount;

	}

    // return number of covered tiles adjacent to this tile
    adjacentCoveredCount(tile) {

        let coveredCount = 0;
        for (let adjTile of this.getAdjacent(tile)) {
			//if (adjTile.isCovered() && !adjTile.isFlagged()) {
			if (adjTile.isCovered() && !adjTile.isSolverFoundBomb()) {
                coveredCount++;
            }
        }

        return coveredCount;

    }

	// header for messages sent to the server
	getMessageHeader() {
        return { "id": this.id, "width": this.width, "height": this.height, "mines": this.num_bombs, "seed": this.seed, "gametype" : this.gameType};
	}
	
	// returns all the tiles adjacent to this tile
	getAdjacent(tile) {
		
		const col = tile.x;
		const row = tile.y;

		const first_row = Math.max(0, row - 1);
		const last_row = Math.min(this.height - 1, row + 1);

		const first_col = Math.max(0, col - 1);
		const last_col = Math.min(this.width - 1, col + 1);

		const result = []

		for (let r = first_row; r <= last_row; r++) {
			for (let c = first_col; c <= last_col; c++) {
				if (!(r == row && c == col)) {  // don't include ourself
					const i = this.width * r + c;
					result.push(this.tiles[i]);
				}
			}
		}

		return result;
	}

	getFlagsPlaced() {

		let tally = 0;
		for (let i = 0; i < this.tiles.length; i++) {
			if (this.tiles[i].isFlagged()) {
				tally++;
            }
        }
			 
		return tally;
    }

	// sets up the initial tiles 
	init_tiles() {
		
		for (let y=0; y < this.height; y++) {
			for (let x=0; x < this.width; x++) {
				this.tiles.push(new Tile(x, y, y * this.width + x));
			}
		}
		
	}

	setAllZero() {
		for (let i = 0; i < this.tiles.length; i++) {
			this.tiles[i].setValue(0);
		}
    }

	hasSafeTile() {
		for (let i = 0; i < this.tiles.length; i++) {
			const tile = this.tiles[i];
			if (tile.getHasHint() && tile.probability == 1) {
				return true;
            }
		}

		return false;
	}

	getSafeTiles() {
		const result = [];

		for (let i = 0; i < this.tiles.length; i++) {
			const tile = this.tiles[i];
			if (tile.getHasHint() && tile.probability == 1) {
				result.push(new Action(tile.getX(), tile.getY(), 1, ACTION_CLEAR));
			}
		}

		return result;
	}

	// optionally treat flags as mines (e.g. in analysis mode but not playing or replay)
	// place mines when they are trivially found
	// The idea is to get the board into a state as pobability engine friendly as possible
	// If an invalid tile is found returns it to be reported
	resetForAnalysis(flagIsMine, findObviousMines) {

		//const start = Date.now();

		for (let i = 0; i < this.tiles.length; i++) {
			const tile = this.tiles[i];

			if (!tile.isCovered() && tile.isFlagged()) {
				console.warn(tile.asText() + " is flagged but not covered! Resetting to covered.");
				tile.setCovered(true);
			}

			if (tile.isFlagged()) {
				tile.foundBomb = flagIsMine;
			} else {
				tile.foundBomb = false;
			}
		}

		if (!findObviousMines) {
			return null;
        }

		for (let i = 0; i < this.tiles.length; i++) {

			const tile = this.getTile(i);

			if (tile.isCovered()) {
				if (this.isTileAMine(tile)) {  // a tile is an obvious mine if every adjacent witness agrees it is
					tile.setFoundBomb();  
                }
				continue;  // if the tile hasn't been revealed yet then nothing to consider
			}

			const adjTiles = this.getAdjacent(tile);

			let flagCount = 0;
			let coveredCount = 0;
			for (let j = 0; j < adjTiles.length; j++) {
				const adjTile = adjTiles[j];
				if (adjTile.isCovered()) {
					coveredCount++;
				}
				if (adjTile.isFlagged()) {
					flagCount++;
                }
			}

			if (coveredCount > 0 && tile.getValue() == coveredCount) { // can place all flags
				//for (let j = 0; j < adjTiles.length; j++) {
				//	const adjTile = adjTiles[j];
				//	if (adjTile.isCovered()) { // if covered 
				//		adjTile.setFoundBomb();   // Must be a bomb
				//	}
				//}
			} else if (tile.getValue() < flagCount) {
				//console.log(tile.asText() + " is over flagged");
			} else if (tile.getValue() > coveredCount) {
				//console.log(tile.asText() + " has an invalid value of " + tile.getValue() + " with only " + coveredCount + " surrounding covered tiles");
				return tile;
            }

		}	

		//console.log("Reset for Analysis took " + (Date.now() - start) + " milliseconds");

		return null;
    }

	// if every witness around this tile agrees it is a mine, then set it as a mine
	isTileAMine(tile) {

		const adjTiles = this.getAdjacent(tile);

		let witnessCount = 0;
		for (let j = 0; j < adjTiles.length; j++) {
			const adjTile = adjTiles[j];

			if (adjTile.isCovered()) {
				continue;
			}

			witnessCount++;

			// if this witness denies all the remaining hidden tiles are mines then don't continue
			if (!this.checkWitness(adjTile)) {
				return false;
            }

		}

		if (witnessCount == 0) {
			return false;

		} else {  // all the adjacent witnesses agree that this tile is a mine
			return true;
        }

		


    }

	// see if this witness thinks all adjacent hidden ties are mines
	checkWitness(tile) {

		const adjTiles = this.getAdjacent(tile);

		let coveredCount = 0;
		for (let j = 0; j < adjTiles.length; j++) {
			const adjTile = adjTiles[j];
			if (adjTile.isCovered()) {
				coveredCount++;
			}
		}

		if (coveredCount > 0 && tile.getValue() == coveredCount) { // only room left for mines
			return true;
		}

    }

	getHashValue() {

		let hash = (31 * 31 * 31 * this.num_bombs + 31 * 31 * this.getFlagsPlaced() + 31 * this.width + this.height) % this.MAX;

		for (let i = 0; i < this.tiles.length; i++) {
			const tile = this.tiles[i];
			if (tile.isFlagged()) {
				hash = (31 * hash + 13) % this.MAX;
			} else if (tile.isCovered()) {
				hash = (31 * hash + 12) % this.MAX;
			} else {
				hash = (31 * hash + tile.getValue()) % this.MAX;
			}
        }

		return hash;
	}

	// returns a string that represents this board state which can be save and restored later
	getStateData() {

		// wip

		for (var i = 0; i < this.tiles.length; i++) {
			var tile = this.tiles[i];
			if (tile.isFlagged()) {
				hash = (31 * hash + 13) % this.MAX;
			} else if (tile.isCovered()) {
				hash = (31 * hash + 12) % this.MAX;
			} else {
				hash = (31 * hash + tile.getValue()) % this.MAX;
			}
		}


	}

	findAutoMove() {

		const result = new Map();

		for (let i = 0; i < this.tiles.length; i++) {

			const tile = this.getTile(i);

			if (tile.isFlagged()) {
				continue;  // if the tile is a mine then nothing to consider
			} else if (tile.isCovered()) {
				continue;  // if the tile hasn't been revealed yet then nothing to consider
			}

			const adjTiles = this.getAdjacent(tile);

			let needsWork = false;
			let flagCount = 0;
			let coveredCount = 0;
			for (let j = 0; j < adjTiles.length; j++) {
				const adjTile = adjTiles[j];
				if (adjTile.isCovered() && !adjTile.isFlagged()) {
					needsWork = true;
				}
				if (adjTile.isFlagged()) {
					flagCount++;
				} else if (adjTile.isCovered()) {
					coveredCount++;
                }
			}

			if (needsWork) {  // the witness still has some unrevealed adjacent tiles
				if (tile.getValue() == flagCount) {  // can clear around here
					for (let j = 0; j < adjTiles.length; j++) {
						const adjTile = adjTiles[j];
						if (adjTile.isCovered() && !adjTile.isFlagged()) {
							result.set(adjTile.index, new Action(adjTile.getX(), adjTile.getY(), 1, ACTION_CLEAR));
						}
					}			

				} else if (tile.getValue() == flagCount + coveredCount) { // can place all flags
					for (let j = 0; j < adjTiles.length; j++) {
						const adjTile = adjTiles[j];
						if (adjTile.isCovered() && !adjTile.isFlagged()) { // if covered and isn't flagged
							adjTile.setFoundBomb();   // Must be a bomb
							result.set(adjTile.index, new Action(adjTile.getX(), adjTile.getY(), 0, ACTION_FLAG));
						}
					}			
                }
			}

		}	

		// send it back as an array
		return Array.from(result.values());

	} 

	getFormatMBF() {

		if (this.width > 255 || this.height > 255) {
			console.log("Board too large to save as MBF format");
			return null;
        }

		const length = 4 + 2 * this.num_bombs;

		const mbf = new ArrayBuffer(length);
		const mbfView = new Uint8Array(mbf);

		mbfView[0] = this.width;
		mbfView[1] = this.height;

		mbfView[2] = Math.floor(this.num_bombs / 256);
		mbfView[3] = this.num_bombs % 256;

		let minesFound = 0;
		let index = 4;
		for (let i = 0; i < this.tiles.length; i++) {

			const tile = this.getTile(i);

			if (tile.isFlagged()) {
				minesFound++;
				if (index < length) {
					mbfView[index++] = tile.getX();
					mbfView[index++] = tile.getY();
                }
			}
		}

		if (minesFound != this.num_bombs) {
			console.log("Board has incorrect number of mines. board=" + this.num_bombs + ", found=" + minesFound);
			return null;
		}

		console.log(...mbfView);

		return mbf;

    }

	getPositionData() {

		const newLine = "\n";

		let data = this.width + "x" + this.height + "x" + this.num_bombs + newLine;

		for (let y = 0; y < this.height; y++) {
			for (let x = 0; x < this.width; x++) {
				const tile = this.getTileXY(x, y);
				if (tile.isFlagged()) {
					data = data + "F";

				} else if (tile.isCovered() && !tile.isBomb()) {
					data = data + "H";

				} else if (tile.isBomb()) {
					data = data + "?";

				} else {
					data = data + tile.getValue();
                } 
			}
			data = data + newLine;
        }

		return data;

    }

	// this version of the compression only deflates flags which don't result in values < 0
	getSimpleCompressedData() {

		const start = Date.now();

		// The games dimensions
		const width = this.width;
		const height = this.height;
		const mines = this.num_bombs;

		// an array to do the processing
		let a = [];

		// transfer the values into an array
		for (let y = 0; y < height; y++) {

			let xa = [];

			for (let x = 0; x < width; x++) {
				const tile = this.getTileXY(x, y);

				if (tile.isFlagged()) {
					xa.push(10);  // placed flag

				} else if (tile.isCovered() || tile.isBomb()) { // a covered tile, or an exploded mine
					xa.push(9);  // hidden

				} else {
					xa.push(tile.getValue());  // revealed

				}
			}
			a.push(xa);
		}

		// find obvious mines not flagged, we need these otherwise we can't deflate games with NF style 
		for (let y = 0; y < height; y++) {
			for (let x = 0; x < width; x++) {

				const value = a[y][x];

				if (value < 9) {
					const ys = Math.max(0, y - 1);
					const ye = Math.min(height - 1, y + 1);

					const xs = Math.max(0, x - 1);
					const xe = Math.min(width - 1, x + 1);

					let spaces = 0;
					for (let y1 = ys; y1 <= ye; y1++) {
						for (let x1 = xs; x1 <= xe; x1++) {
							if (a[y1][x1] > 8) {
								spaces++;
							}
						}
					}
					if (spaces == value) { // if the number of spaces equals the value then anything unflagged is a 'hidden flag'
						//console.log(x + " " + y + " " + value + " " + spaces);
						for (let y1 = ys; y1 <= ye; y1++) {
							for (let x1 = xs; x1 <= xe; x1++) {
								if (a[y1][x1] == 9) {
									//console.log( "-- " + x1 + " " + y1);
									a[y1][x1] = 11;  // a trivially found mine but not flagged
								}
							}
						}
					}

				}
			}
		}

		// see which flags can be deflated
		for (let y = 0; y < height; y++) {
			for (let x = 0; x < width; x++) {

				const value = a[y][x];

				if (value == 10 || value == 11) {
					const ys = Math.max(0, y - 1);
					const ye = Math.min(height - 1, y + 1);

					const xs = Math.max(0, x - 1);
					const xe = Math.min(width - 1, x + 1);

					// check that all the adjacent revealed tiles can be reduced (i.e. not already zero)
					let okay = true;
					for (let y1 = ys; y1 <= ye; y1++) {
						for (let x1 = xs; x1 <= xe; x1++) {
							if (a[y1][x1] == 0) {
								okay = false
							}
						}
					}
					if (okay) { // every adjacent revealed tile can be reduced by 1
						for (let y1 = ys; y1 <= ye; y1++) {
							for (let x1 = xs; x1 <= xe; x1++) {
								if (a[y1][x1] < 9) {
									a[y1][x1]--;
								}
							}
						}
					} else {
						if (a[y][x] == 10) {  // placed flag that overflags a revealed tile
							a[y][x] = 12;  // overflagged ==> flag that isn't inflated

						} else if (a[y][x] == 11) {  // hidden flag that overflags a revealed tile
							a[y][x] = 9;  // revert back to a hidden tile
						} 
						
					}

				}
			}
		}

		let data = "";

		// convert to a string
		for (let y = 0; y < height; y++) {
			for (let x = 0; x < width; x++) {

				const value = a[y][x];

				if (value == 10) { // flagged and deflated
					data = data + "F";

				} else if (value == 11) { // a mine is here but not flagged, deflated 
					data = data + "I";

				} else if (value == 12) { // a flag which wasn't deflated
					data = data + "O";

				} else if (value == 9) {  // a hidden tile
					data = data + "H";

				} else { // a revealed tile's value (after deflation)
					data = data + value;
				}
			}
		}

		// get a compressor class
		//const compressor = new Compressor();

		// compress the data to base 62
		let cWidth = this.compressor.compressNumber(width, 2);
		let cHeight = this.compressor.compressNumber(height, 2);
		let cMines = this.compressor.compressNumber(mines, 4);

		let cBoard = this.compressor.compress(data);

		let output = cWidth + cHeight + cMines + cBoard;

		//console.log("Compressed data length " + output.length + " analysis=" + output);
		//console.log("Time to compress " + (Date.now() - start) + " milliseconds");

		return output;

	}

	getCompressedData(reduceMines) {

		// this identifies obvious mines
		this.resetForAnalysis(false, true);

		let data = "";

		let reducedMines = 0;

		for (let y = 0; y < this.height; y++) {
			for (let x = 0; x < this.width; x++) {
				const tile = this.getTileXY(x, y);

				if (tile.isSolverFoundBomb()) {
					// an enclosed certain mine can be set to '0'
					if (reduceMines && this.adjacentCoveredCount(tile) == 0) {
						data = data + "0";
						reducedMines++;

					// otherwise set to Flagged, or 'I' = Hidden + Inflate
					} else {
						if (tile.isFlagged()) {
							data = data + "F";
						} else {
							data = data + "I"
                        }
                    }


				} else if (tile.isFlagged()) {
					data = data + "F";

				} else if (tile.isCovered() || tile.isBomb()) {
					data = data + "H";

				} else {
					//let reduceBy = this.adjacentFlagsPlaced(tile);

					let reduceBy = 0;
					for (let adjTile of this.getAdjacent(tile)) {
						if (adjTile.isFlagged() || adjTile.isSolverFoundBomb()) {
							reduceBy++;
						}
					}

					if (reduceBy > tile.getValue()) {
						console.log(tile.asText() + " has too many flags around it, can't compress invalid data");
						return "";
                    }
					data = data + (tile.getValue() - reduceBy);
				}
			}
		}

		let cWidth = this.compressor.compressNumber(this.width, 2);
		let cHeight = this.compressor.compressNumber(this.height, 2);
		let cMines = this.compressor.compressNumber(this.num_bombs - reducedMines, 4);

		let cBoard = this.compressor.compress(data);

		let output = cWidth + cHeight + cMines + cBoard;

		console.log("Compressed data length " + output.length + " analysis=" + output);

		return output;

	}

}

class Compressor {

	constructor() {
		this.BASE62 = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";

		// this array decides how many digits to allocate to each value on the board
		// [0, 1, 2, 3, 4, 5, 6, 7, 8, hidden flag, HIDDEN, FLAG, overflagged]
		this.VALUES = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "I", "H", "F", "O"];
		this.BASES = [10, 7, 5, 5, 4, 3, 3, 1, 1, 4, 10, 8, 1];
		this.digits = [];

		let start = 0;
		for (const n of this.BASES) {
			this.digits.push(this.BASE62.substring(start, start + n));
			start = start + n;
        }

		//console.log(this.digits);

    }

	compress(input) {

		let output = "";

		let count = 0;
		let prevChar = "";
		for (let i = 0; i < input.length; i++) {
			let currChar = input.charAt(i);

			if (prevChar == "") {
				prevChar = currChar;
				count = 1;

            } else if (currChar == prevChar) {
				count++;

			} else {
				// add the compressed data
				output = output + this.compressFragment(prevChar, count);

				// start counting the new data
				prevChar = currChar;
				count = 1;
            }
        }

		// add the final compressed data
		output = output + this.compressFragment(prevChar, count);

		//console.log("Compressed data length " + output.length + " data: " + output);

		return output;

	}

	// compress 'length' characters 'char'
	compressFragment(char, length) {

		// find the compression details

		let index = this.VALUES.indexOf(char);
		if (index == -1) {
			console.log("Unable to find the value '" + char + "' in the compression values array");
			return "";
        }

		let digits = this.digits[index];
		let base = digits.length;

		// for values with only 1 allocated value return that value 'length' times.
		if (base == 1) {
			return digits.repeat(length);
        }

		let output = "";

		while (length != 0) {

			let digit = length % base;
			output = digits[digit] + output;

			length = (length - digit) / base;

        }

		//console.log(output);

		return output;
    }

	decompress(input) {

		let output = "";

		let count = 0;
		let prevChar = "";
		for (let i = 0; i < input.length; i++) {

			let testChar = input.charAt(i);

			let index = this.digits.findIndex((element) => element.includes(testChar));

			// the value this character represents and the count it represents
			let currChar = this.VALUES[index];
			let currCount = this.digits[index].indexOf(testChar);
			let base = this.digits[index].length;

			if (prevChar == "") {
				prevChar = currChar;
				count = currCount;

			} else if (currChar == prevChar) {
				if (base == 1) {
					count++;
				} else {
					count = count * base + currCount;
                }

			} else {
				// add the compressed data
				output = output + prevChar.repeat(count);

				// start counting the new data
				prevChar = currChar;

				if (base == 1) {
					count = 1;
				} else {
					count = currCount;
				}
			}
		}

		// add the final compressed data
		output = output + prevChar.repeat(count);

		//console.log("Decompressed data length " + output.length + " data: " + output);

		return output;

	}

	compressNumber(number, size) {

		const base = this.BASE62.length;

		let output = "";
		for (let i = 0; i < size; i++) {

			let digit = number % base;
			output = this.BASE62[digit] + output;
			number = (number - digit) / base;

        }

		return output;

	}

	decompressNumber(value) {

		const base = this.BASE62.length;

		let output = 0;
		for (let i = 0; i < value.length; i++) {

			let digit = this.BASE62.indexOf(value.charAt(i));

			output = output * base + digit ;

		}

		return output;

	}
}
/**
 * 
 */
"use strict";

class Tile {
	constructor(x, y, index) {
		this.x = x;
		this.y = y;
		this.is_covered = true;
		this.value = 0;
		this.is_flagged = false;
		this.foundBomb = false
        this.is_bomb = null;   // this gets set when the game is lost
		this.exploded = false;  // this gets set if this tile was the one clicked

		this.isSafe = false;
		this.isNextMove = false;   // set when this tile is one the next moves to be played

		this.index = index;
		this.is_start = false;

        this.onEdge = false;
        this.hint = false;
        this.probability = -1;  // of being safe
		this.hintText = "";
		this.hasHint = false;

		this.efficiencyValue = "";   // the value we need to be to be chordable
		this.efficiencyProbability = 0;  // the probability of being that value
		this.efficiencyText = "";  

		this.winRate = 0;   // win rate as determined by the Brute force analysis
		this.winRateText = "";  

		this.zeroProbability = 0;
		this.zeroPoison = false;

		this.valueProbability = Array(9).fill(0);

		// is there an mine adjacent to this tile?  Set as part of the No flag efficiency logic
		this.adjacentMine = false;

		this.skull = false;  // used when hardcore rule triggers

		this.inflate = false; // used when constructing a compressed board

		Object.seal(this); // prevent new values being created
	}

	getX() {
		return this.x;
	}
	
	getY() {
		return this.y;
	}
	
	// returns true if the tile provided is adjacent to this tile
	isAdjacent(tile) {
		
		const dx = Math.abs(this.x - tile.x);
		const dy = Math.abs(this.y - tile.y);
		
		// adjacent and not equal
		if (dx < 2 && dy < 2 && !(dx == 0 && dy == 0)) {
			return true;
		} else {
			return false;
		}
		
	}

    isEqual(tile) {

        if (this.x == tile.x && this.y == tile.y) {
            return true;
        } else {
            return false;
        }

    }

	asText() {
		return "(" + this.x + "," + this.y + ")";
	}

    getHintText() {

        if (!this.hasHint) {
            return "";
		} else {
			return this.hintText + this.efficiencyText + this.winRateText;
        }

    }

	getHasHint() {
		return this.hasHint;
    }

    setProbability(prob, progress, safety2) {
        this.probability = prob;
        this.hasHint = true;

		if (prob == 1) {
			this.hintText = "Safe";
		} else if (prob == 0) {
			this.hintText = "Mine";
		} else if (progress == null) {
			this.hintText = "\n" + (prob * 100).toFixed(2) + "% safe";
		} else {
			this.hintText = "\n" + (prob * 100).toFixed(2) + "% safe" + "\n" + (safety2 * 100).toFixed(2) + "% 2nd safety" + "\n" + (progress * 100).toFixed(2) + "% progress"
        }

	}

	setValueProbability(value, probability) {
		this.efficiencyValue = value;
		this.efficiencyProbability = probability;

		this.efficiencyText = "\n" + (probability * 100).toFixed(2) + "% value '" + value + "'"
	}

	setWinRate(winRate) {
		this.winRate = winRate;

		this.winRateText = "\n" + (winRate * 100).toFixed(2) + "% solve rate";
	}

    //getProbability() {
    //    return this.probability;
    //}

    clearHint() {
        this.onEdge = false;
        this.hasHint = false;
		this.hintText = "";
		this.efficiencyValue = null;
		this.efficiencyProbability = 0;
		this.efficiencyText = "";
		this.probability = -1;
		this.winRate = 0;
		this.winRateText = "";
		this.zeroPoison = false;
		this.isNextMove = false;
		this.isSafe = false;
    }

	setOnEdge() {
		//console.log(this.asText() + " Setting on edge");
        this.onEdge = true;
    }

	isOnEdge() {
		return this.onEdge;
	}

	isCovered() {
		return this.is_covered;
	}

	setCovered(covered) {
		//console.log(this.asText() + " covered: " + covered);
		this.is_covered = covered;
    }

	setValue(value) {
		//console.log(this.asText() + " setting value " + value + " and not covered");
		this.value = value;
		this.is_covered = false;
	}

	setValueOnly(value) {
		if (this.is_flagged) {
			console.error(this.asText() + " assigning a value " + value + " to a flagged tile!");
		}

		this.value = value;
    }

	getValue() {
		return this.value;
	}

	rotateValue(delta) {

		var newValue = this.value + delta;

		if (newValue < 0) {
			newValue = 8;
		} else if (newValue > 8) {
			newValue = 0;
        }

		this.setValue(newValue);
    }

	toggleFlag() {
		this.is_flagged = !this.is_flagged;
	}
	
	isFlagged() {
		return this.is_flagged;
	}

	// this is set when the solver discovers a bomb - trying to separate the discovery of a bomb from the flagging of a tile
	setFoundBomb() {
		//console.log(this.asText() + " set to Found Bomb");
		this.foundBomb = true;
	}

	// this is used when a tile is speculatively set to a mine to see if the board is still valid
	unsetFoundBomb() {
		//console.log(this.asText() + " set to not Found Bomb");
		this.foundBomb = false;
	}

	isSolverFoundBomb() {
		return this.foundBomb;
    }

	// this is used to display the bombs when the game is lost
	setBomb(bomb) {
		this.is_bomb = bomb;
	}

	// this is used to display the exploded bomb when the game is lost
    setBombExploded() {
        this.is_bomb = true;
        this.exploded = true;
    }

	isBomb() {
		return this.is_bomb;
	}

	setSkull(isSkull) {
		this.skull = isSkull;
	}

	isSkull() {
		return this.skull;
    }
}